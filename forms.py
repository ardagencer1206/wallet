# forms.py
from flask_wtf import FlaskForm
from wtforms import (
    StringField, PasswordField, SubmitField, DecimalField, TextAreaField, HiddenField
)
from wtforms.validators import DataRequired, Email, Length, Optional
from flask import request
from decimal import Decimal


# ---- Auth ----
class RegisterForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Şifre", validators=[DataRequired(), Length(min=6)])
    submit = SubmitField("Kayıt Ol")


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Şifre", validators=[DataRequired()])
    submit = SubmitField("Giriş Yap")


# ---- Transfer ----
class TransferForm(FlaskForm):
    to_email = StringField("Alıcı Email", validators=[DataRequired(), Email()])
    amount = DecimalField("Miktar (SRDS)", places=2, validators=[DataRequired()])
    message = TextAreaField("Mesaj", validators=[Optional()])
    submit = SubmitField("Gönder")


# ---- Exchange (BUY/SELL) ----
class ExchangeForm(FlaskForm):
    # HTML tarafı değişmeyecek.
    side = HiddenField(validators=[Optional()])

    # Her iki alan Optional. Eşik kontrolleri validate() içinde.
    amount_try = DecimalField("TRY Tutarı", places=2, validators=[Optional()])
    amount_srds = DecimalField("SRDS Tutarı", places=2, validators=[Optional()])

    submit_buy = SubmitField("Satın Al")
    submit_sell = SubmitField("Sat")

    def _determine_side(self) -> str:
        if "submit_buy" in request.form:
            return "buy"
        if "submit_sell" in request.form:
            return "sell"
        v = (self.side.data or "").strip().lower()
        if v in {"buy", "sell"}:
            return v
        v2 = (request.form.get("side", "") or "").strip().lower()
        return v2 if v2 in {"buy", "sell"} else ""

    @staticmethod
    def _gt_zero(val) -> bool:
        try:
            return (val is not None) and (Decimal(val) > 0)
        except Exception:
            return False

    def validate(self, **kwargs):
        if not super().validate(**kwargs):
            return False

        side = self._determine_side()
        if not side:
            self.side.errors.append("İşlem tipi tespit edilemedi.")
            return False

        # Karşı alanı HER ZAMAN yok say. (HTML değişmeden çalışır)
        if side == "buy":
            # Tahmini SRDS input’u gönderilse bile temizle.
            self.amount_srds.data = None
            self.amount_srds.errors = []
        else:  # sell
            # Yanlışlıkla TRY gönderilse bile temizle.
            self.amount_try.data = None
            self.amount_try.errors = []

        # Artık sadece ilgili alanı kontrol et.
        if side == "buy":
            if not self._gt_zero(self.amount_try.data):
                self.amount_try.errors.append("Alış için TRY tutarı > 0 olmalı.")
                return False
        else:  # sell
            if not self._gt_zero(self.amount_srds.data):
                self.amount_srds.errors.append("Satış için SRDS tutarı > 0 olmalı.")
                return False

        return True
