from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.fields import EmailField
from wtforms.validators import InputRequired, EqualTo, Length, Regexp, Optional


class LoginForm(FlaskForm):
    username = StringField('Username', validators=[InputRequired()])
    password = PasswordField('Password', validators=[InputRequired()])
    submit = SubmitField('Login')


class RegisterForm(FlaskForm):
    username = StringField('Username',
                           validators=[InputRequired(),
                                       Length(4, 64),
                                       Regexp('^[A-Za-z][A-Za-z0-9_.]*$', 0,
                                              'Usernames must start with a letter and must have only letters, '
                                              'numbers, dots or underscores')])
    email = EmailField('Email', validators=[InputRequired()])
    phone = StringField('Phone number', validators=[InputRequired()])
    password = PasswordField('Password', validators=[InputRequired(), Length(8)])
    confirmPassword = PasswordField('Confirm Password',
                                    validators=[InputRequired(),
                                                EqualTo('password',
                                                        message='Passwords must match.')])
    submit = SubmitField('Register')


class AccountForm(FlaskForm):
    username = StringField('Username', render_kw={'readonly': True})
    email = EmailField('Email', validators=[InputRequired()])
    phone = StringField('Phone number', validators=[InputRequired()])
    oldPassword = PasswordField('Old Password', validators=[InputRequired()])
    newPassword = PasswordField('New Password', validators=[InputRequired(), Length(8)])
    submit = SubmitField('Save')