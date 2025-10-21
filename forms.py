# forms.py
from flask_wtf import FlaskForm
from wtforms import (
    StringField, PasswordField, SubmitField, TextAreaField, HiddenField
)
from wtforms.validators import DataRequired, Email, Length, Optional
from wtforms.fields import DecimalField
from flask import request
from decimal import Decimal, InvalidOperation


# ---- helpers ----
def _none_if_blank_or_zero(v):
    if v is None:
        return None
    s = str(v).strip()
    if s in ("", "0", "0.0", "0.00"):
        return None
    return v


class ZeroAsNoneDecimalField(DecimalField):
    """'0' / '0.00' gönderilirse data=None yap."""
    def process_formdata(self, valuelist):
        super().process_formdata(valuelist)
        try:
            if self.data is None:
                return
            if isinstance(self.data, Decimal):
                if self.data == Decimal("0"):
                    self.data = None
            else:
                # float/int geldi ise
                if float(self.data) == 0.0:
                    self.data = None
        except (InvalidOperation, ValueError):
            self.data = None


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
    amount = ZeroAsNoneDecimalField("Miktar (SRDS)", places=2, validators=[DataRequired()])
    message = TextAreaField("Mesaj", validators=[Optional()])
    submit = SubmitField("Gönder")


# ---- Exchange (BUY/SELL) ----
class ExchangeForm(FlaskForm):
    # HTML’de:
    #  <!-- BUY -->
    #  <form method="post">{% raw %}{{ form.hidden_tag() }}{% endraw %}<input type="hidden" name="side" value="buy">
    #     {% raw %}{{ form.amount_try }}{{ form.submit_buy }}{% endraw %}</form>
    #  <!-- SELL -->
    #  <form method="post">{% raw %}{{ form.hidden_tag() }}{% endraw %}<input type="hidden" name="side" value="sell">
    #     {% raw %}{{ form.amount_srds }}{{ form.submit_sell }}{% endraw %}</form>
    side = HiddenField(validators=[Optional()])

    amount_try  = ZeroAsNoneDecimalField("TRY Tutarı",  places=2, validators=[Optional()], filters=[_none_if_blank_or_zero], render_kw={"inputmode": "decimal"})
    amount_srds = ZeroAsNoneDecimalField("SRDS Tutarı", places=2, validators=[Optional()], filters=[_none_if_blank_or_zero], render_kw={"inputmode": "decimal"})

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

        # Yan alan “0 / boş” ise temizle (buy → SRDS, sell → TRY)
        if side == "buy" and (self.amount_srds.data in (None, Decimal("0"))):
            self.amount_srds.data = None
            self.amount_srds.errors = []
        if side == "sell" and (self.amount_try.data in (None, Decimal("0"))):
            self.amount_try.data = None
            self.amount_try.errors = []

        # İki alan aynı anda doluysa reddet.
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
                self.amount_srds.errors.append("Alışta SRDS alanını boş bırakın.")
                return False

        else:  # sell
            # SELL: SRDS > 0 zorunlu, TRY boş olmalı
            if not self._gt_zero(self.amount_srds.data):
                self.amount_srds.errors.append("Satış için SRDS tutarı > 0 olmalı.")
                return False
            if self.amount_try.data is not None:
                self.amount_try.errors.append("Satışta TRY alanını boş bırakın.")
                return False

        return True
