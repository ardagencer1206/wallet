from flask_wtf import FlaskForm 
from wtforms import (
    StringField, PasswordField, SubmitField, DecimalField, TextAreaField, HiddenField
)
from wtforms.validators import DataRequired, Email, Length, Optional, NumberRange
from flask import request

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
    # HiddenField ile, işlem tipini almak için
    side = HiddenField(validators=[Optional()])

    amount_try = DecimalField("TRY Tutarı", places=2, validators=[Optional(), NumberRange(min=0.01)])
    amount_srds = DecimalField("SRDS Tutarı", places=2, validators=[Optional(), NumberRange(min=0.01)])

    # Submit butonları
    submit_buy = SubmitField("Satın Al")
    submit_sell = SubmitField("Sat")

    def validate(self, **kwargs):
        ok = super().validate(**kwargs)
        if not ok:
            return False

        # Butonlara göre hangi işlem yapıldığını kontrol et
        pressed_buy = "submit_buy" in request.form
        pressed_sell = "submit_sell" in request.form
        side_val = (self.side.data or "").strip().lower()

        # Buy işlemi için TRY tutarının zorunlu olması
        if pressed_buy or side_val == "buy":
            if not self.amount_try.data:
                self.amount_try.errors.append("Alış için TRY tutarı girin.")
                return False
        
        # Sell işlemi için SRDS tutarının zorunlu olması
        elif pressed_sell or side_val == "sell":
            if not self.amount_srds.data:
                self.amount_srds.errors.append("Satış için SRDS tutarı girin.")
                return False

        # Hangi işlem olduğu belirtilmemişse
        else:
            self.side.errors.append("İşlem tipi tespit edilemedi.")
            return False

        return True
