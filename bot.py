import os
import tweepy
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.getenv("ACCESS_TOKEN_SECRET")

print("DEBUG API_KEY is None? ->", API_KEY is None)

def create_client_v2():
    return tweepy.Client(
        consumer_key=API_KEY,
        consumer_secret=API_SECRET,
        access_token=ACCESS_TOKEN,
        access_token_secret=ACCESS_TOKEN_SECRET
    )


def main():
    client = create_client_v2()
    text = "テスト投稿 : GitHub + Render 自動投稿ボットからの投稿です。"
    response = client.create_tweet(text=text)
    print("投稿完了:", response)

if __name__ == "__main__":
    main()
