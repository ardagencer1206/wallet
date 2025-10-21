from flask_wtf import FlaskForm
from wtforms import (
    StringField, PasswordField, SubmitField, DecimalField, TextAreaField, HiddenField
)
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
    amount = DecimalField("Miktar (SRDS)", places=2,
                          validators=[DataRequired(), NumberRange(min=0.01)])
    message = TextAreaField("Mesaj", validators=[Optional()])
    submit = SubmitField("Gönder")


class ExchangeForm(FlaskForm):
    # HTML tarafında:
    #  - Alış formu içinde:  <input type="hidden" name="side" value="buy">
    #  - Satış formu içinde: <input type="hidden" name="side" value="sell">
    side = HiddenField(validators=[DataRequired(message="İşlem tipi eksik.")])

    amount_try = DecimalField("TRY Tutarı", places=2,
                              validators=[Optional(), NumberRange(min=0.01, message="En az 0.01 olmalı.")])
    amount_srds = DecimalField("SRDS Tutarı", places=2,
                               validators=[Optional(), NumberRange(min=0.01, message="En az 0.01 olmalı.")])

    submit_buy = SubmitField("Satın Al")
    submit_sell = SubmitField("Sat")

    def validate(self, **kwargs):
        ok = super().validate(**kwargs)
        if not ok:
            return False

        side_val = (self.side.data or "").strip().lower()
        if side_val == "buy":
            if not self.amount_try.data:
                self.amount_try.errors.append("Alış için TRY tutarı girin.")
                return False
        elif side_val == "sell":
            if not self.amount_srds.data:
                self.amount_srds.errors.append("Satış için SRDS tutarı girin.")
                return False
        else:
            self.side.errors.append("Geçersiz işlem.")
            return False

        return True
