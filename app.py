import os
from decimal import Decimal

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

    def upsert_srds_value():
        # user id=11 TRY / circulating_supply
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

    def get_price():
        rec = SrdsValue.query.first()
        if rec and rec.value and Decimal(rec.value) > 0:
            return Decimal(rec.value)
        return upsert_srds_value()

    with app.app_context():
        db.create_all()
        inspector = inspect(db.engine)

        # user.balance yoksa
        cols = [c["name"] for c in inspector.get_columns("user")]
        if "balance" not in cols:
            db.session.execute(text(
                "ALTER TABLE `user` ADD COLUMN `balance` DECIMAL(18,2) NOT NULL DEFAULT 0.00"
            ))
            db.session.commit()

        # user.try_balance yoksa
        cols = [c["name"] for c in inspector.get_columns("user")]
        if "try_balance" not in cols:
            db.session.execute(text(
                "ALTER TABLE `user` ADD COLUMN `try_balance` DECIMAL(18,2) NOT NULL DEFAULT 0.00"
            ))
            db.session.commit()

        # transfer_history.message yoksa
        cols = [c["name"] for c in inspector.get_columns("transfer_history")]
        if "message" not in cols:
            db.session.execute(text(
                "ALTER TABLE `transfer_history` ADD COLUMN `message` VARCHAR(500) NULL"
            ))
            db.session.commit()

        # Komisyon havuzu
        if not db.session.get(CommissionPool, 1):
            db.session.add(CommissionPool(id=1, total=Decimal("0.00")))
            db.session.commit()

        # CirculatingSupply init + hesap
        if not db.session.get(CirculatingSupply, 1):
            db.session.add(CirculatingSupply(id=1, total=Decimal("0.00")))
            db.session.commit()
        recalc_supply()

        # srds_value satırı yoksa oluştur ve güncelle
        if not SrdsValue.query.first():
            db.session.add(SrdsValue(value=Decimal("0")))
            db.session.commit()
        upsert_srds_value()

    # Tüm şablonlara srds_value enjekte
    @app.context_processor
    def inject_srds_value():
        try:
            val = get_price()
        except Exception:
            db.session.rollback()
            row = SrdsValue.query.first()
            val = row.value if row else Decimal("0")
        return {"srds_value": val}

    # -------- Routes --------
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

                cs = db.session.get(CirculatingSupply, 1)
                if cs:
                    cs.total = (Decimal(cs.total) - fee).quantize(Decimal("0.01"))
                else:
                    total = db.session.query(func.coalesce(func.sum(User.balance), 0)).scalar() or 0
                    db.session.add(CirculatingSupply(id=1, total=Decimal(total).quantize(Decimal("0.01"))))

                db.session.commit()
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
        form = ExchangeForm()
        price = get_price()
        if form.validate_on_submit():
            side = form.side.data  # 'buy' | 'sell'
            if price <= 0:
                flash("Fiyat tanımsız.", "danger")
                return render_template("exchange.html", form=form, price=price)

            fee_rate = Decimal("0.002")  # %0.2
            KASA_ID = 11

            try:
                me = db.session.execute(
                    select(User).where(User.id == current_user.id).with_for_update()
                ).scalar_one()
                kasa = db.session.execute(
                    select(User).where(User.id == KASA_ID).with_for_update()
                ).scalar_one()
                pool = db.session.execute(
                    select(CommissionPool).where(CommissionPool.id == 1).with_for_update()
                ).scalar_one()
                cs = db.session.execute(
                    select(CirculatingSupply).where(CirculatingSupply.id == 1).with_for_update()
                ).scalar_one()

                if side == "buy":
                    amt_try = (form.amount_try.data or Decimal("0")).quantize(Decimal("0.01"))
                    if amt_try <= 0:
                        flash("Geçersiz TRY tutarı.", "danger"); db.session.rollback()
                        return render_template("exchange.html", form=form, price=price)

                    gross_srds = (amt_try / price).quantize(Decimal("0.01"))
                    fee_srds = (gross_srds * fee_rate).quantize(Decimal("0.01"))
                    net_srds = (gross_srds - fee_srds).quantize(Decimal("0.01"))

                    if me.try_balance < amt_try:
                        flash("TRY bakiyesi yetersiz.", "danger"); db.session.rollback()
                        return render_template("exchange.html", form=form, price=price)
                    if kasa.balance < gross_srds:
                        flash("Yetersiz SRDS likiditesi.", "danger"); db.session.rollback()
                        return render_template("exchange.html", form=form, price=price)

                    # TRY hareketi
                    me.try_balance = (Decimal(me.try_balance) - amt_try).quantize(Decimal("0.01"))
                    kasa.try_balance = (Decimal(kasa.try_balance) + amt_try).quantize(Decimal("0.01"))
                    # SRDS hareketi
                    kasa.balance = (Decimal(kasa.balance) - gross_srds).quantize(Decimal("0.01"))
                    me.balance = (Decimal(me.balance) + net_srds).quantize(Decimal("0.01"))
                    # Komisyon SRDS havuza
                    pool.total = (Decimal(pool.total) + fee_srds).quantize(Decimal("0.01"))
                    # Supply komisyon kadar düşer
                    cs.total = (Decimal(cs.total) - fee_srds).quantize(Decimal("0.01"))

                    db.session.commit()
                    upsert_srds_value()

                    flash(f"{amt_try} TRY ile {net_srds} SRDS alındı. Komisyon {fee_srds} SRDS.", "success")
                    return redirect(url_for("home"))

                else:  # sell
                    amt_srds = (form.amount_srds.data or Decimal("0")).quantize(Decimal("0.01"))
                    if amt_srds <= 0:
                        flash("Geçersiz SRDS tutarı.", "danger"); db.session.rollback()
                        return render_template("exchange.html", form=form, price=price)

                    # Kullanıcının SRDS'ine ek olarak %0.2 komisyon SRDS tahsil edilir
                    fee_srds = (amt_srds * fee_rate).quantize(Decimal("0.01"))
                    total_srds_debit = (amt_srds + fee_srds).quantize(Decimal("0.01"))

                    # TRY ödemesi satılan miktar (amt_srds) üstünden hesaplanır
                    gross_try = (amt_srds * price).quantize(Decimal("0.01"))

                    # Bakiye ve likidite kontrolleri
                    if me.balance < total_srds_debit:
                        flash("SRDS bakiyesi yetersiz (komisyon dahil).", "danger"); db.session.rollback()
                        return render_template("exchange.html", form=form, price=price)
                    if kasa.try_balance < gross_try:
                        flash("Yetersiz TRY likiditesi.", "danger"); db.session.rollback()
                        return render_template("exchange.html", form=form, price=price)

                    # SRDS: tamamı havuza, ek olarak komisyon da havuza
                    me.balance = (Decimal(me.balance) - total_srds_debit).quantize(Decimal("0.01"))
                    pool.total = (Decimal(pool.total) + total_srds_debit).quantize(Decimal("0.01"))
                    # Dolaşımdan düşüş: satılan + komisyon
                    cs.total = (Decimal(cs.total) - total_srds_debit).quantize(Decimal("0.01"))
                    # TRY kasa -> kullanıcı
                    kasa.try_balance = (Decimal(kasa.try_balance) - gross_try).quantize(Decimal("0.01"))
                    me.try_balance = (Decimal(me.try_balance) + gross_try).quantize(Decimal("0.01"))

                    db.session.commit()
                    upsert_srds_value()

                    flash(f"{amt_srds} SRDS satıldı. {gross_try} TRY yatırıldı. Komisyon {fee_srds} SRDS (ek olarak tahsil edildi).", "success")
                    return redirect(url_for("home"))

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
