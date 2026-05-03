"""A tiny random CLI app for demo recording."""

from __future__ import annotations

import secrets


LOWER_BOUND = 1
UPPER_BOUND = 10


def main() -> None:
    secret = secrets.randbelow(UPPER_BOUND - LOWER_BOUND + 1) + LOWER_BOUND
    attempts = 0
    print("Number Guessing Game")
    print(f"I picked a number between {LOWER_BOUND} and {UPPER_BOUND}.")

    while True:
        raw_guess = input("Guess> ").strip()
        attempts += 1

        try:
            guess = int(raw_guess)
        except ValueError:
            print("Please enter a whole number.")
            continue

        if guess < secret:
            print("Too low. Try a bigger number.")
        elif guess > secret:
            print("Too high. Try a smaller number.")
        else:
            print(f"You got it in {attempts} guesses.")
            print("Thanks for playing.")
            return


if __name__ == "__main__":
    main()
