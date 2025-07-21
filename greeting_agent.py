from agno.agent import Agent
from textwrap import dedent
from agno.models.google import Gemini
import os
from dotenv import load_dotenv
import sqlite3

# Connect to your database
conn = sqlite3.connect("./data/synthetic_health_data_with_cgm.db")  # Make sure it's in the same directory
cursor = conn.cursor()

# Load environment variables from .env file
load_dotenv()

# Access the API key
gemini_api_key = os.getenv("GEMINI_API_KEY")


# Create the Gemini model instance
gemini_model = Gemini(id="gemini-2.5-pro", api_key=gemini_api_key)

# Set up the base agent
greetings_agent = Agent(
    model=gemini_model,
    instructions=dedent("""\
        You are a warm and friendly assistant. Your job is to get the user's name and greet them personally.
        Ask for the user's name if you don’t know it yet.
        Once you know the name, greet them like: "Hello <name>! Nice to meet you 😊"
        Do not ask for the name again after greeting.
    """),
    add_datetime_to_instructions=False,
    markdown=True,
)

mood_tracker_agent = Agent(
    model=gemini_model,
    instructions=dedent("""\
        You are a helpful assistant that detects the user's mood based on what they say.
        Extract only the mood/emotion they are expressing (e.g., happy, sad, anxious, excited, tired).
        Respond only with the mood as a single word. No extra explanations or text.
    """),
    add_datetime_to_instructions=False,
    markdown=False,
)

# Function to fetch name from DB using user_id
def get_name_from_user_id(user_id):
    cursor.execute("SELECT FirstName, LastName FROM Individuals WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result if result else (None, None)

def log_user_mood(user_id, user_input):
    try:
        mood_response = mood_tracker_agent.run(user_input)
        mood = mood_response.content.strip().lower()
        
        print(f"📝 Mood '{mood}' obtained from the agent for user {user_id}")
        # Insert into MoodLogs table
        cursor.execute("INSERT INTO MoodLogs (user_id, mood) VALUES (?, ?)", (user_id, mood))
        conn.commit()

        print(f"📝 Mood '{mood}' logged for user {user_id}")
    except Exception as e:
        print(f"⚠️ Failed to detect mood: {e}")


# Function to run interaction
def run_agent():
    print("🤖: Hi! Please enter your user ID to begin.")
    user_id = input("👤 (Enter your user ID): ").strip()

    first_name, last_name = get_name_from_user_id(user_id)

    print(first_name,last_name )

    if first_name and last_name:
        full_input = f"My name is {first_name} {last_name}"
        response = greetings_agent.run(full_input)
        print(f"🤖: {response.content}")
    else:
        print("🤖: Sorry, I couldn't find that user ID. Please check and try again.")
    
    # Ask for mood
    print("🤖: How are you feeling today?")
    mood_input = input("👤: ")

    # Log mood
    log_user_mood(user_id, mood_input)


run_agent()
