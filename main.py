import secrets
import string


def generate_password(length: int = 16, use_special: bool = True) -> str:
    alphabet = string.ascii_letters + string.digits
    if use_special:
        alphabet += "!@#$%^&*()-_=+"

    # Гарантируем надежную криптографическую случайность
    password = "".join(secrets.choice(alphabet) for _ in range(length))
    return password


if __name__ == "__main__":
    print("Generated token / password:")
    print(generate_password(20))
