from flask_wtf import FlaskForm
from wtforms import (
    StringField, PasswordField, SubmitField, DecimalField, TextAreaField, RadioField
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
    side = RadioField(
        "İşlem",
        choices=[("buy", "SRDS Al (TRY → SRDS)"), ("sell", "SRDS Sat (SRDS → TRY)")],
        default="buy",
        validators=[DataRequired()],
    )
    amount_try = DecimalField("TRY Tutarı", places=2,
                              validators=[Optional(), NumberRange(min=0.01)])
    amount_srds = DecimalField("SRDS Tutarı", places=2,
                               validators=[Optional(), NumberRange(min=0.01)])

    # Ayrı butonlar: HTML'de "submit_buy" ve "submit_sell" kullanılabiliyor
    submit_buy = SubmitField("Satın Al")
    submit_sell = SubmitField("Sat")

    def validate(self, **kwargs):
        ok = super().validate(**kwargs)
        if not ok:
            return False

        if self.side.data == "buy":
            if not self.amount_try.data:
                self.amount_try.errors.append("Alış için TRY tutarı girin.")
                return False
        elif self.side.data == "sell":
            if not self.amount_srds.data:
                self.amount_srds.errors.append("Satış için SRDS tutarı girin.")
                return False
        else:
            self.side.errors.append("Geçersiz işlem.")
            return False
        return True
