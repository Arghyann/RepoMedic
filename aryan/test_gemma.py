from dotenv import load_dotenv

# Load GOOGLE_API_KEY from .env
load_dotenv()

from google import genai

client = genai.Client()

# Using Google's Gemma model
interaction = client.interactions.create(
    model="gemini-3.8-flash",
    input="Explain how AI works in a few words"
)

print(interaction.output_text)
