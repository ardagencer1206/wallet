import os
from flask import Flask, render_template, redirect, url_for, flash, request
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from models import db, User
from forms import RegisterForm, LoginForm, TransferForm
from sqlalchemy import inspect, text   # eklendi
from sqlalchemy.exc import NoResultFound
from decimal import Decimal

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
        return User.query.get(int(user_id))

    with app.app_context():
        db.create_all()

        # balance sütunu yoksa tabloya ekle
        inspector = inspect(db.engine)
        cols = [c['name'] for c in inspector.get_columns('user')]
        if 'balance' not in cols:
            db.session.execute(
                text("ALTER TABLE user ADD COLUMN balance DECIMAL(18,2) NOT NULL DEFAULT 0.00")
            )
            db.session.commit()

    @app.route("/")
    def home():
        return render_template("home.html")

    @app.route("/register", methods=["GET","POST"])
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

    @app.route("/login", methods=["GET","POST"])
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
    
    @app.route("/transfer", methods=["GET","POST"])
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

            # Atomik işlem + satır kilidi
            try:
                from sqlalchemy import select
                sender = db.session.execute(
                    select(User).where(User.id == current_user.id).with_for_update()
                ).scalar_one()
                receiver = db.session.execute(
                    select(User).where(User.id == to_user.id).with_for_update()
                ).scalar_one()

                if sender.balance < amount:
                    flash("Bakiye yetersiz.", "danger")
                    db.session.rollback()
                    return redirect(url_for("transfer"))

                sender.balance = (Decimal(sender.balance) - amount).quantize(Decimal("0.01"))
                receiver.balance = (Decimal(receiver.balance) + amount).quantize(Decimal("0.01"))
                db.session.commit()
                flash(f"{to_email} adresine {amount} SRDS gönderildi.", "success")
                return redirect(url_for("home"))
            except NoResultFound:
                db.session.rollback()
                flash("İşlem sırasında kullanıcı bulunamadı.", "danger")
            except Exception:
                db.session.rollback()
                flash("İşlem başarısız.", "danger")

        return render_template("transfer.html", form=form)

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("home"))

    return app

if __name__ == "__main__":
    app = create_app()
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
