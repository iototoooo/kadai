import os

from openai import OpenAI

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

def chat(user_message, history):
    history.append({"role": "user", "content": user_message})

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=history
    )

    assistant_message = response.choices[0].message.content
    history.append({"role": "assistant", "content": assistant_message})

    return assistant_message, history

def main():
    print("ChatGPT チャット (終了するには 'exit' と入力)")
    print("-" * 40)

    history = [{"role": "system", "content": "You are a helpful assistant. Please respond in Japanese."}]

    while True:
        user_input = input("あなた: ").strip()

        if user_input.lower() in ("quit", "exit", "終了"):
            print("終了します。")
            break

        if not user_input:
            continue

        response, history = chat(user_input, history)
        print(f"ChatGPT: {response}\n")

if __name__ == "__main__":
    main()
