# forms.py
from flask_wtf import FlaskForm
from wtforms import (
    StringField, PasswordField, SubmitField, DecimalField, TextAreaField, HiddenField
)
from wtforms.validators import DataRequired, Email, Length, Optional
from flask import request


# -------- Auth -------- #
class RegisterForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Şifre", validators=[DataRequired(), Length(min=6)])
    submit = SubmitField("Kayıt Ol")


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Şifre", validators=[DataRequired()])
    submit = SubmitField("Giriş Yap")


# -------- Transfer -------- #
class TransferForm(FlaskForm):
    to_email = StringField("Alıcı Email", validators=[DataRequired(), Email()])
    amount = DecimalField("Miktar (SRDS)", places=2, validators=[DataRequired()])
    message = TextAreaField("Mesaj", validators=[Optional()])
    submit = SubmitField("Gönder")


# -------- Exchange (BUY/SELL) -------- #
class ExchangeForm(FlaskForm):
    # HTML:
    #  <form method="post"> {{ form.hidden_tag() }} <input type="hidden" name="side" value="buy"> ... </form>
    #  <form method="post"> {{ form.hidden_tag() }} <input type="hidden" name="side" value="sell"> ... </form>
    side = HiddenField(validators=[Optional()])

    # İki alanda da sadece Optional. Eşik kontrolleri validate() içinde yapılır.
    amount_try = DecimalField("TRY Tutarı", places=2, validators=[Optional()], render_kw={"inputmode": "decimal"})
    amount_srds = DecimalField("SRDS Tutarı", places=2, validators=[Optional()], render_kw={"inputmode": "decimal"})

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
            return (val is not None) and (val > 0)
        except Exception:
            return False

    def validate(self, **kwargs):
        if not super().validate(**kwargs):
            return False

        side = self._determine_side()
        if not side:
            self.side.errors.append("İşlem tipi tespit edilemedi.")
            return False

        # Karşı alanın kazara "0" gelmesi durumunda görmezden gel.
        if side == "buy" and (self.amount_srds.data == 0 or self.amount_srds.data is None):
            self.amount_srds.data = None
        if side == "sell" and (self.amount_try.data == 0 or self.amount_try.data is None):
            self.amount_try.data = None

        # Aynı anda iki alan doluysa reddet.
        if self.amount_try.data and self.amount_srds.data:
            self.amount_try.errors.append("Aynı anda iki tutarı girmeyin.")
            self.amount_srds.errors.append("Aynı anda iki tutarı girmeyin.")
            return False

        if side == "buy":
            # BUY: TRY > 0 zorunlu, SRDS boş olmalı
            if not self._gt_zero(self.amount_try.data):
                self.amount_try.errors.append("Alış için TRY tutarı > 0 olmalı.")
                return False
            if self.amount_srds.data is not None:
                self.amount_srds.errors.append("Alış işleminde SRDS tutarı girmeyin.")
                return False

        elif side == "sell":
            # SELL: SRDS > 0 zorunlu, TRY boş olmalı
            if not self._gt_zero(self.amount_srds.data):
                self.amount_srds.errors.append("Satış için SRDS tutarı > 0 olmalı.")
                return False
            if self.amount_try.data is not None:
                self.amount_try.errors.append("Satış işleminde TRY tutarı girmeyin.")
                return False

        return True
