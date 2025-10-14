from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, DecimalField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, Optional


class RegisterForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Şifre", validators=[DataRequired(), Length(min=6)])
    submit = SubmitField("Kayıt Ol")

class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Şifre", validators=[DataRequired()])
    submit = SubmitField("Giriş Yap")
class TransferForm(FlaskForm):
    to_email = StringField("Alıcı Email", validators=[DataRequired(), Email()])
    amount = DecimalField("Miktar (SRDS)", places=2, validators=[DataRequired(), NumberRange(min=0.01)])
    message = TextAreaField("Mesaj", validators=[Optional()]) 
    submit = SubmitField("Gönder")
