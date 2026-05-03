"""A tiny deterministic CLI app for demo recording."""

from __future__ import annotations


def main() -> None:
    secret = 7
    attempts = 0
    print("Number Guessing Game")
    print("I picked a number between 1 and 10.")

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
