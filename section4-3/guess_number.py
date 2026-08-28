import random

def main():
    print("=== 数当てゲーム ===")
    print("1〜100の数字を当ててください！")

    answer = random.randint(1, 100)
    attempts = 0

    while True:
        try:
            guess = int(input("\n数字を入力: "))
        except ValueError:
            print("整数を入力してください。")
            continue

        if guess < 1 or guess > 100:
            print("1〜100の範囲で入力してください。")
            continue

        attempts += 1

        if guess < answer:
            print("もっと大きい！")
        elif guess > answer:
            print("もっと小さい！")
        else:
            print(f"正解！ 🎉 {attempts}回で当てました！")
            break

if __name__ == "__main__":
    main()
