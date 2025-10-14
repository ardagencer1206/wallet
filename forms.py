from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email, Length

class RegisterForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Şifre", validators=[DataRequired(), Length(min=6)])
    submit = SubmitField("Kayıt Ol")

class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Şifre", validators=[DataRequired()])
    submit = SubmitField("Giriş Yap")
