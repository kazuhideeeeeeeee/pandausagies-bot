import os
import tweepy
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("pnBPfESa9gXarM9lIZW4RCDXz")
API_SECRET = os.getenv("bRk5t7h7VGXWiRiBroGuixWO9ERA2jfgdGQCjHMX7l8zesopKM")
ACCESS_TOKEN = os.getenv("1988900673572974592-nbefOZcMbZ1vt2MyL2q9xPiQE4wYkk")
ACCESS_TOKEN_SECRET = os.getenv("ZtLmzo4GP5zhoxnBpaGzNZsYH9ppl4JfEz4j3Kz0Zp00t")

def create_client_v2():
    return tweepy.Client(
        consumer_key=API_KEY,
        consumer_secret=API_SECRET,
        access_token=ACCESS_TOKEN,
        access_token_secret=ACCESS_TOKEN_SECRET
    )

def main():
        client = create_client_v2()
        text = "テスト投稿：GitHub + Render 自動投稿ボットからの投稿です。"
        response = client.create_tweet(text=text)
        print("投稿完了:", response)

if __name__ == "__main__":
    main()
