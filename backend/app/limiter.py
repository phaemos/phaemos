from slowapi import Limiter
from slowapi.util import get_remote_address

# I instantiate the limiter once here so main.py and individual routes both import
# the same object — slowapi requires the same Limiter instance to be registered on
# the app.state and used in route decorators.
limiter = Limiter(key_func=get_remote_address)
