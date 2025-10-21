# forms.py
from flask_wtf import FlaskForm
from wtforms import (
    StringField, PasswordField, SubmitField, DecimalField, TextAreaField, HiddenField
)
from wtforms.validators import DataRequired, Email, Length, Optional, NumberRange
from flask import request


# ------- Auth ------- #
class RegisterForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Şifre", validators=[DataRequired(), Length(min=6)])
    submit = SubmitField("Kayıt Ol")


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Şifre", validators=[DataRequired()])
    submit = SubmitField("Giriş Yap")


# ------- Transfer ------- #
class TransferForm(FlaskForm):
    to_email = StringField("Alıcı Email", validators=[DataRequired(), Email()])
    amount = DecimalField(
        "Miktar (SRDS)",
        places=2,
        validators=[DataRequired(), NumberRange(min=0.01, message="Miktar 0'dan büyük olmalı.")]
    )
    message = TextAreaField("Mesaj", validators=[Optional()])
    submit = SubmitField("Gönder")


# ------- Exchange (BUY/SELL) ------- #
class ExchangeForm(FlaskForm):
    # HTML:
    #  <form method="post"> {{ form.hidden_tag() }} <input type="hidden" name="side" value="buy"> ... </form>
    #  <form method="post"> {{ form.hidden_tag() }} <input type="hidden" name="side" value="sell"> ... </form>
    side = HiddenField(validators=[Optional()])

    amount_try = DecimalField(
        "TRY Tutarı",
        places=2,
        validators=[Optional(), NumberRange(min=0.01, message="Tutar 0'dan büyük olmalı.")]
    )
    amount_srds = DecimalField(
        "SRDS Tutarı",
        places=2,
        validators=[Optional(), NumberRange(min=0.01, message="Tutar 0'dan büyük olmalı.")]
    )

    submit_buy = SubmitField("Satın Al")
    submit_sell = SubmitField("Sat")

    def _determine_side(self) -> str:
        # Öncelik: basılan buton -> hidden side -> request param
        if "submit_buy" in request.form:
            return "buy"
        if "submit_sell" in request.form:
            return "sell"
        val = (self.side.data or "").strip().lower()
        if val in {"buy", "sell"}:
            return val
        val2 = (request.form.get("side", "") or "").strip().lower()
        if val2 in {"buy", "sell"}:
            return val2
        return ""

    def validate(self, **kwargs):
        if not super().validate(**kwargs):
            return False

        side = self._determine_side()
        if not side:
            self.side.errors.append("İşlem tipi tespit edilemedi.")
            return False

        both_filled = bool(self.amount_try.data) and bool(self.amount_srds.data)
        none_filled = not self.amount_try.data and not self.amount_srds.data
        if both_filled:
            self.amount_try.errors.append("Aynı anda iki tutarı birden girmeyin.")
            self.amount_srds.errors.append("Aynı anda iki tutarı birden girmeyin.")
            return False
        if none_filled:
            # Hangi tarafsa ona göre mesaj
            if side == "buy":
                self.amount_try.errors.append("Alış için TRY tutarı girin.")
            else:
                self.amount_srds.errors.append("Satış için SRDS tutarı girin.")
            return False

        if side == "buy":
            # BUY: TRY zorunlu, SRDS boş
            if not self.amount_try.data:
                self.amount_try.errors.append("Alış için TRY tutarı girin.")
                return False
            if self.amount_srds.data:
                self.amount_srds.errors.append("Alış işleminde SRDS tutarı girmeyin.")
                return False

        elif side == "sell":
            # SELL: SRDS zorunlu, TRY boş
            if not self.amount_srds.data:
                self.amount_srds.errors.append("Satış için SRDS tutarı girin.")
                return False
            if self.amount_try.data:
                self.amount_try.errors.append("Satış işleminde TRY tutarı girmeyin.")
                return False

        return True
