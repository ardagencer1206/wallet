import os
from decimal import Decimal, InvalidOperation

from flask import Flask, render_template, redirect, url_for, flash, request
from flask_login import LoginManager, login_user, login_required, logout_user, current_user

from sqlalchemy import inspect, text, select, func
from sqlalchemy.exc import NoResultFound

from models import (
    db, User, CommissionPool, TransferHistory, Notification,
    CirculatingSupply, SrdsValue
)
from forms import RegisterForm, LoginForm, TransferForm, ExchangeForm
from qrgenerate import generate_qr


def mysql_url_from_railway():
    host = os.getenv("MYSQLHOST")
    user = os.getenv("MYSQLUSER")
    password = os.getenv("MYSQLPASSWORD")
    database = os.getenv("MYSQLDATABASE")
    port = os.getenv("MYSQLPORT", "3306")
    if all([host, user, password, database]):
        return f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}?charset=utf8mb4"
    return os.getenv("DATABASE_URL", "mysql+pymysql://root:password@127.0.0.1:3306/appdb?charset=utf8mb4")


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret")
    app.config["SQLALCHEMY_DATABASE_URI"] = mysql_url_from_railway()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    login_manager = LoginManager()
    login_manager.login_view = "login"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # ---- helpers ----
    def recalc_supply():
        total = db.session.query(func.coalesce(func.sum(User.balance), 0)).scalar() or 0
        cs = db.session.get(CirculatingSupply, 1)
        if not cs:
            cs = CirculatingSupply(id=1, total=Decimal(total))
            db.session.add(cs)
        else:
            cs.total = Decimal(total).quantize(Decimal("0.01"))
        db.session.commit()

    def current_price() -> Decimal:
        row = SrdsValue.query.first()
        try:
            return Decimal(row.value) if row and row.value is not None else Decimal("0")
        except Exception:
            return Decimal("0")

    def upsert_srds_value():
        """ user id=11 try_balance / circulating_supply """
        kasa = db.session.get(User, 11) or User.query.filter_by(email="sardisiumkasasi@gmail.com").first()
        circ = db.session.get(CirculatingSupply, 1)
        value = Decimal("0")
        if kasa and circ and Decimal(circ.total or 0) > 0:
            value = (Decimal(kasa.try_balance or 0) / Decimal(circ.total)).quantize(Decimal("0.00000001"))
        row = SrdsValue.query.first()
        if row:
            row.value = value
        else:
            db.session.add(SrdsValue(value=value))
        db.session.commit()
        return value

    with app.app_context():
        db.create_all()
        inspector = inspect(db.engine)

        # user.balance
        cols = [c["name"] for c in inspector.get_columns("user")]
        if "balance" not in cols:
            db.session.execute(text(
                "ALTER TABLE `user` ADD COLUMN `balance` DECIMAL(18,2) NOT NULL DEFAULT 0.00"
            ))
            db.session.commit()
        # user.try_balance
        cols = [c["name"] for c in inspector.get_columns("user")]
        if "try_balance" not in cols:
            db.session.execute(text(
                "ALTER TABLE `user` ADD COLUMN `try_balance` DECIMAL(18,2) NOT NULL DEFAULT 0.00"
            ))
            db.session.commit()
        # transfer_history.message
        cols = [c["name"] for c in inspector.get_columns("transfer_history")]
        if "message" not in cols:
            db.session.execute(text(
                "ALTER TABLE `transfer_history` ADD COLUMN `message` VARCHAR(500) NULL"
            ))
            db.session.commit()

        # havuz init
        if not db.session.get(CommissionPool, 1):
            db.session.add(CommissionPool(id=1, total=Decimal("0.00")))
            db.session.commit()

        # supply + price init
        if not db.session.get(CirculatingSupply, 1):
            db.session.add(CirculatingSupply(id=1, total=Decimal("0.00")))
            db.session.commit()
        recalc_supply()

        if not SrdsValue.query.first():
            db.session.add(SrdsValue(value=Decimal("0")))
            db.session.commit()
        upsert_srds_value()

    # tüm şablonlara srds_value
    @app.context_processor
    def inject_srds_value():
        try:
            val = upsert_srds_value()
        except Exception:
            db.session.rollback()
            row = SrdsValue.query.first()
            val = row.value if row else Decimal("0")
        return {"srds_value": val}

    # -------- routes --------
    @app.route("/")
    def home():
        return render_template("home.html")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for("home"))
        form = RegisterForm()
        if form.validate_on_submit():
            if User.query.filter_by(email=form.email.data).first():
                flash("Email zaten kayıtlı.", "danger")
                return redirect(url_for("register"))
            user = User(email=form.email.data)
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
            flash("Kayıt başarılı. Giriş yapın.", "success")
            return redirect(url_for("login"))
        return render_template("register.html", form=form)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("home"))
        form = LoginForm()
        if form.validate_on_submit():
            user = User.query.filter_by(email=form.email.data).first()
            if user and user.check_password(form.password.data):
                login_user(user, remember=True)
                return redirect(request.args.get("next") or url_for("home"))
            flash("Geçersiz bilgiler.", "danger")
        return render_template("login.html", form=form)

    @app.route("/transfer", methods=["GET", "POST"])
    @login_required
    def transfer():
        form = TransferForm()
        if form.validate_on_submit():
            to_email = form.to_email.data.strip().lower()
            amount = (form.amount.data or Decimal("0")).quantize(Decimal("0.01"))

            if to_email == current_user.email.lower():
                flash("Kendinize gönderemezsiniz.", "danger")
                return redirect(url_for("transfer"))

            to_user = User.query.filter_by(email=to_email).first()
            if not to_user:
                flash("Alıcı bulunamadı.", "danger")
                return redirect(url_for("transfer"))

            fee = (amount / Decimal("500")).quantize(Decimal("0.01"))
            total_debit = (amount + fee).quantize(Decimal("0.01"))

            try:
                sender = db.session.execute(
                    select(User).where(User.id == current_user.id).with_for_update()
                ).scalar_one()
                receiver = db.session.execute(
                    select(User).where(User.id == to_user.id).with_for_update()
                ).scalar_one()
                pool = db.session.execute(
                    select(CommissionPool).where(CommissionPool.id == 1).with_for_update()
                ).scalar_one()

                if sender.balance < total_debit:
                    flash("Bakiye yetersiz.", "danger")
                    db.session.rollback()
                    return redirect(url_for("transfer"))

                sender.balance = (Decimal(sender.balance) - total_debit).quantize(Decimal("0.01"))
                receiver.balance = (Decimal(receiver.balance) + amount).quantize(Decimal("0.01"))
                pool.total = (Decimal(pool.total) + fee).quantize(Decimal("0.01"))

                history = TransferHistory(
                    sender_id=sender.id,
                    receiver_id=receiver.id,
                    amount=amount,
                    commission=fee,
                    message=(form.message.data or "").strip() if getattr(form, "message", None) else None,
                )
                db.session.add(history)

                notif = Notification(
                    sender_id=sender.id,
                    receiver_id=receiver.id,
                    amount=amount,
                    message=(form.message.data or "").strip() if getattr(form, "message", None) else None,
                )
                db.session.add(notif)

                db.session.commit()
                # supply + value
                recalc_supply()
                upsert_srds_value()

                flash(f"{to_email} adresine {amount} SRDS gönderildi.", "success")
                return redirect(url_for("home"))

            except NoResultFound:
                db.session.rollback()
                flash("İşlem sırasında kullanıcı bulunamadı.", "danger")
            except Exception:
                db.session.rollback()
                flash("İşlem başarısız.", "danger")

        return render_template("transfer.html", form=form)

    @app.route("/exchange", methods=["GET", "POST"])
    @login_required
    def exchange():
        """Kasa (user id=11) karşı taraf. BUY: TRY->SRDS, SELL: SRDS->TRY."""
        form = ExchangeForm()
        price = current_price()  # TRY per 1 SRDS

        if request.method == "POST" and form.validate_on_submit():
            action = form.action.data  # "BUY" or "SELL"
            # Form: BUY için amount TRY, SELL için amount SRDS
            try:
                amt = Decimal(form.amount.data)
            except (InvalidOperation, TypeError):
                flash("Geçersiz tutar.", "danger")
                return render_template("exchange.html", form=form, price=price)

            if price <= 0:
                flash("Geçerli bir SRDS fiyatı yok.", "danger")
                return render_template("exchange.html", form=form, price=price)

            # kasa
            treasury = db.session.get(User, 11) or User.query.filter_by(email="sardisiumkasasi@gmail.com").first()
            if not treasury:
                flash("Kasa bulunamadı.", "danger")
                return render_template("exchange.html", form=form, price=price)

            COMM = Decimal("1") / Decimal("500")  # %0.2

            try:
                user = db.session.execute(
                    select(User).where(User.id == current_user.id).with_for_update()
                ).scalar_one()
                kasa = db.session.execute(
                    select(User).where(User.id == treasury.id).with_for_update()
                ).scalar_one()
                pool = db.session.execute(
                    select(CommissionPool).where(CommissionPool.id == 1).with_for_update()
                ).scalar_one()

                # supply satırı hazır olsun
                cs = db.session.get(CirculatingSupply, 1)
                if not cs:
                    total = db.session.query(func.coalesce(func.sum(User.balance), 0)).scalar() or 0
                    cs = CirculatingSupply(id=1, total=Decimal(total).quantize(Decimal("0.01")))
                    db.session.add(cs)
                    db.session.flush()

                if action == "BUY":
                    # Kullanıcı TRY öder, kasadan SRDS alır. Komisyon SRDS cinsinden.
                    amount_try = amt.quantize(Decimal("0.01"))
                    srds_gross = (amount_try / price).quantize(Decimal("0.01"))  # balance 2 hane
                    fee_srds = (srds_gross * COMM).quantize(Decimal("0.01"))
                    srds_net = (srds_gross - fee_srds).quantize(Decimal("0.01"))

                    # kontroller
                    if Decimal(user.try_balance) < amount_try:
                        flash("TRY bakiyesi yetersiz.", "danger")
                        db.session.rollback()
                        return render_template("exchange.html", form=form, price=price)
                    if Decimal(kasa.balance) < srds_gross:
                        flash("Kasa SRDS bakiyesi yetersiz.", "danger")
                        db.session.rollback()
                        return render_template("exchange.html", form=form, price=price)

                    # hareketler
                    user.try_balance = (Decimal(user.try_balance) - amount_try).quantize(Decimal("0.01"))
                    kasa.try_balance = (Decimal(kasa.try_balance) + amount_try).quantize(Decimal("0.01"))

                    kasa.balance = (Decimal(kasa.balance) - srds_gross).quantize(Decimal("0.01"))
                    user.balance = (Decimal(user.balance) + srds_net).quantize(Decimal("0.01"))

                    pool.total = (Decimal(pool.total) + fee_srds).quantize(Decimal("0.01"))

                    db.session.commit()

                elif action == "SELL":
                    # Kullanıcı SRDS satar, kasadan TRY alır. Komisyon SRDS cinsinden.
                    amount_srds = amt.quantize(Decimal("0.01"))
                    fee_srds = (amount_srds * COMM).quantize(Decimal("0.01"))
                    srds_net_to_kasa = (amount_srds - fee_srds).quantize(Decimal("0.01"))
                    try_out = (amount_srds * price).quantize(Decimal("0.01"))

                    # kontroller
                    if Decimal(user.balance) < amount_srds:
                        flash("SRDS bakiyesi yetersiz.", "danger")
                        db.session.rollback()
                        return render_template("exchange.html", form=form, price=price)
                    if Decimal(kasa.try_balance) < try_out:
                        flash("Kasa TRY bakiyesi yetersiz.", "danger")
                        db.session.rollback()
                        return render_template("exchange.html", form=form, price=price)

                    # hareketler
                    user.balance = (Decimal(user.balance) - amount_srds).quantize(Decimal("0.01"))
                    kasa.balance = (Decimal(kasa.balance) + srds_net_to_kasa).quantize(Decimal("0.01"))
                    pool.total = (Decimal(pool.total) + fee_srds).quantize(Decimal("0.01"))

                    kasa.try_balance = (Decimal(kasa.try_balance) - try_out).quantize(Decimal("0.01"))
                    user.try_balance = (Decimal(user.try_balance) + try_out).quantize(Decimal("0.01"))

                    db.session.commit()

                else:
                    flash("Geçersiz işlem.", "danger")
                    return render_template("exchange.html", form=form, price=price)

                # supply'u yeniden hesapla ve fiyatı güncelle
                recalc_supply()
                upsert_srds_value()

                flash("İşlem tamamlandı.", "success")
                return redirect(url_for("exchange"))

            except Exception:
                db.session.rollback()
                flash("İşlem başarısız.", "danger")

        return render_template("exchange.html", form=form, price=price)

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("home"))

    @app.route("/history")
    @login_required
    def history():
        stmt = (
            select(TransferHistory, User.email)
            .join(User, User.id == TransferHistory.receiver_id)
            .where(TransferHistory.sender_id == current_user.id)
            .order_by(TransferHistory.created_at.desc())
        )
        results = db.session.execute(stmt).all()
        history_rows = [{
            "to_email": to_email,
            "amount": transfer.amount,
            "commission": transfer.commission,
            "created_at": transfer.created_at
        } for transfer, to_email in results]
        return render_template("history.html", history=history_rows)

    @app.route("/qr")
    @login_required
    def qr():
        email = current_user.email
        qr_code = generate_qr(email)
        return render_template("qr.html", qr_code=qr_code, email=email)

    @app.route("/notifications")
    @login_required
    def notifications():
        notifs = (
            db.session.query(Notification, User.email)
            .join(User, User.id == Notification.sender_id)
            .filter(Notification.receiver_id == current_user.id)
            .order_by(Notification.created_at.desc())
            .all()
        )
        rows = [{
            "from_email": sender_email,
            "amount": notif.amount,
            "message": notif.message,
            "created_at": notif.created_at
        } for notif, sender_email in notifs]
        return render_template("notifications.html", notifications=rows)

    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
