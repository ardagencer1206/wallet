from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, DecimalField, TextAreaField, SelectField
from wtforms.validators import DataRequired, Email, Length, Optional, NumberRange


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


class ExchangeForm(FlaskForm):
    action = SelectField(
        "İşlem",
        choices=[("BUY", "TRY → SRDS (Satın Al)"), ("SELL", "SRDS → TRY (Sat)")],
        validators=[DataRequired()],
    )
    amount = DecimalField("Tutar", places=2, validators=[DataRequired(), NumberRange(min=0.01)])
    submit = SubmitField("Onayla")
