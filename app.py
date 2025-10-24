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
from forms import RegisterForm, LoginForm, TransferForm, BuyForm, SellForm  # SellForm eklendi
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
    # user id 11 HARİÇ
        total = db.session.query(
            func.coalesce(func.sum(User.balance), 0)
        ).filter(User.id != 11).scalar() or 0

        cs = db.session.get(CirculatingSupply, 1)
        if not cs:
            cs = CirculatingSupply(id=1, total=Decimal(total))
            db.session.add(cs)
        else:
            cs.total = Decimal(total).quantize(Decimal("0.01"))
        db.session.commit()


    def upsert_srds_value():
        """user id=11 try_balance / circulating_supply"""
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

        # user.balance yoksa ekle
        cols = [c["name"] for c in inspector.get_columns("user")]
        if "balance" not in cols:
            db.session.execute(text(
                "ALTER TABLE `user` ADD COLUMN `balance` DECIMAL(18,2) NOT NULL DEFAULT 0.00"
            ))
            db.session.commit()

        # user.try_balance yoksa ekle
        cols = [c["name"] for c in inspector.get_columns("user")]
        if "try_balance" not in cols:
            db.session.execute(text(
                "ALTER TABLE `user` ADD COLUMN `try_balance` DECIMAL(18,2) NOT NULL DEFAULT 0.00"
            ))
            db.session.commit()

        # transfer_history.message yoksa ekle
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

    # Tüm şablonlara srds_value enjekte et
    @app.context_processor
    def inject_srds_value():
        try:
            val = upsert_srds_value()
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

            fee = (amount / Decimal("500")).quantize(Decimal("0.01"))  # %0.2
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
            except Exception as e:
                db.session.rollback()
                flash(f"İşlem başarısız: {str(e)}", "danger")

        return render_template("transfer.html", form=form)

    @app.route("/buy", methods=["GET", "POST"])
    @login_required
    def buy():
        form = BuyForm()
        if form.validate_on_submit():
            amount = (form.amount.data or Decimal("0")).quantize(Decimal("0.01"))
            if amount <= 0:
                flash("Geçersiz miktar.", "danger")
                return redirect(url_for("buy"))

            # Güncel fiyat (TRY / SRDS)
            try:
                price = upsert_srds_value()
            except Exception:
                db.session.rollback()
                row = SrdsValue.query.first()
                price = row.value if row else Decimal("0")

            if price is None or Decimal(price) <= 0:
                flash("Fiyat hesaplanamadı.", "danger")
                return redirect(url_for("buy"))

            price = Decimal(price).quantize(Decimal("0.00000001"))
            try_cost_try = (amount * price).quantize(Decimal("0.01"))

            fee_srds = (amount * Decimal("0.007")).quantize(Decimal("0.01"))  # %0.2
            transfer_srds = (amount - fee_srds).quantize(Decimal("0.01"))
            if transfer_srds <= 0:
                flash("Komisyon sonrası miktar sıfırlandı.", "danger")
                return redirect(url_for("buy"))

            try:
                # kilitle
                buyer = db.session.execute(
                    select(User).where(User.id == current_user.id).with_for_update()
                ).scalar_one()

                kasa = db.session.execute(
                    select(User).where(User.id == 11).with_for_update()
                ).scalar_one()

                pool = db.session.execute(
                    select(CommissionPool).where(CommissionPool.id == 1).with_for_update()
                ).scalar_one()

                cs = db.session.get(CirculatingSupply, 1)

                # kontroller
                if Decimal(buyer.try_balance or 0) < try_cost_try:
                    flash("TRY bakiyesi yetersiz.", "danger")
                    db.session.rollback()
                    return redirect(url_for("buy"))

                if Decimal(kasa.balance or 0) < amount:
                    flash("Kasa SRDS bakiyesi yetersiz.", "danger")
                    db.session.rollback()
                    return redirect(url_for("buy"))

                # hareketler
                buyer.try_balance = (Decimal(buyer.try_balance or 0) - try_cost_try).quantize(Decimal("0.01"))
                buyer.balance = (Decimal(buyer.balance or 0) + transfer_srds).quantize(Decimal("0.01"))

                kasa.balance = (Decimal(kasa.balance or 0) - amount).quantize(Decimal("0.01"))
                kasa.try_balance = (Decimal(kasa.try_balance or 0) + try_cost_try).quantize(Decimal("0.01"))

                pool.total = (Decimal(pool.total or 0) + fee_srds).quantize(Decimal("0.01"))

                if cs:
                    cs.total = (Decimal(cs.total or 0) - fee_srds).quantize(Decimal("0.01"))

                # kayıtlar
                db.session.add(TransferHistory(
                    sender_id=kasa.id,
                    receiver_id=buyer.id,
                    amount=transfer_srds,       # kullanıcıya giden net SRDS
                    commission=fee_srds,        # SRDS komisyonu
                    message="BUY SRDS (TRY→SRDS)"
                ))

                db.session.add(Notification(
                    sender_id=kasa.id,
                    receiver_id=buyer.id,
                    amount=transfer_srds,
                    message=f"Satın alma: {try_cost_try} TRY ödendi, {transfer_srds} SRDS alındı. Komisyon: {fee_srds} SRDS."
                ))

                db.session.commit()
                upsert_srds_value()

                flash(f"{try_cost_try} TRY karşılığı {transfer_srds} SRDS alındı. Komisyon: {fee_srds} SRDS.", "success")
                return redirect(url_for("home"))

            except NoResultFound:
                db.session.rollback()
                flash("Kasa veya kullanıcı bulunamadı.", "danger")
            except Exception as e:
                db.session.rollback()
                flash(f"Satın alma başarısız: {str(e)}", "danger")

        return render_template("buy.html", form=form)

    @app.route("/sell", methods=["GET", "POST"])
    @login_required
    def sell():
        form = SellForm()
        if form.validate_on_submit():
            amount = (form.amount.data or Decimal("0")).quantize(Decimal("0.01"))  # satılacak SRDS (brüt)
            if amount <= 0:
                flash("Geçersiz miktar.", "danger")
                return redirect(url_for("sell"))

            # Güncel fiyat (TRY / SRDS)
            try:
                price = upsert_srds_value()
            except Exception:
                db.session.rollback()
                row = SrdsValue.query.first()
                price = row.value if row else Decimal("0")

            if price is None or Decimal(price) <= 0:
                flash("Fiyat hesaplanamadı.", "danger")
                return redirect(url_for("sell"))

            price = Decimal(price).quantize(Decimal("0.00000001"))

            fee_srds = (amount * Decimal("0.007")).quantize(Decimal("0.01"))      # %0.2 SRDS komisyon
            net_srds = (amount - fee_srds).quantize(Decimal("0.01"))               # yakılacak net SRDS
            if net_srds <= 0:
                flash("Komisyon sonrası net miktar sıfırlandı.", "danger")
                return redirect(url_for("sell"))

            try_pay_try = (net_srds * price).quantize(Decimal("0.01"))             # kullanıcıya ödenecek TRY

            try:
                # kilitle
                seller = db.session.execute(
                    select(User).where(User.id == current_user.id).with_for_update()
                ).scalar_one()

                kasa = db.session.execute(
                    select(User).where(User.id == 11).with_for_update()
                ).scalar_one()

                pool = db.session.execute(
                    select(CommissionPool).where(CommissionPool.id == 1).with_for_update()
                ).scalar_one()

                cs = db.session.get(CirculatingSupply, 1)

                # kontroller
                if Decimal(seller.balance or 0) < amount:
                    flash("SRDS bakiyesi yetersiz.", "danger")
                    db.session.rollback()
                    return redirect(url_for("sell"))

                if Decimal(kasa.try_balance or 0) < try_pay_try:
                    flash("Kasa TRY bakiyesi yetersiz.", "danger")
                    db.session.rollback()
                    return redirect(url_for("sell"))

                # hareketler
                # Kullanıcı SRDS'yi satar: tamamı bakiyeden düşer
                seller.balance = (Decimal(seller.balance or 0) - amount).quantize(Decimal("0.01"))
                # Kullanıcı TRY alır
                seller.try_balance = (Decimal(seller.try_balance or 0) + try_pay_try).quantize(Decimal("0.01"))

                # Kasa TRY öder
                kasa.try_balance = (Decimal(kasa.try_balance or 0) - try_pay_try).quantize(Decimal("0.01"))

                # Komisyon havuzu SRDS alır
                pool.total = (Decimal(pool.total or 0) + fee_srds).quantize(Decimal("0.01"))

                # Dolaşımdan düş: satılan toplam SRDS yakıldı
                if cs:
                    cs.total = (Decimal(cs.total or 0) - amount).quantize(Decimal("0.01"))

                # kayıtlar
                db.session.add(TransferHistory(
                    sender_id=seller.id,
                    receiver_id=kasa.id,       # referans amaçlı
                    amount=Decimal("0.00"),    # SRDS transferi yok, yakım var
                    commission=fee_srds,
                    message=f"SELL SRDS (SRDS→TRY). Brüt:{amount} SRDS, Net:{net_srds} SRDS, Ödeme:{try_pay_try} TRY"
                ))

                db.session.add(Notification(
                    sender_id=kasa.id,
                    receiver_id=seller.id,
                    amount=net_srds,
                    message=f"Satış: {amount} SRDS sattınız. Komisyon: {fee_srds} SRDS. Ödeme: {try_pay_try} TRY."
                ))

                db.session.commit()
                upsert_srds_value()

                flash(f"{amount} SRDS satış işlemi tamamlandı. {try_pay_try} TRY ödendi. Komisyon: {fee_srds} SRDS.", "success")
                return redirect(url_for("home"))

            except NoResultFound:
                db.session.rollback()
                flash("Kasa veya kullanıcı bulunamadı.", "danger")
            except Exception as e:
                db.session.rollback()
                flash(f"Satış başarısız: {str(e)}", "danger")

        return render_template("sell.html", form=form)

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
