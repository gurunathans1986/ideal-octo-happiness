from agno.agent import Agent
from textwrap import dedent
from agno.models.google import Gemini
import os
from dotenv import load_dotenv
from datetime import datetime, timezone
from supabase import create_client, Client

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
supabase = create_client(url, key)


DB_PATH = "./data/synthetic_health_data_with_cgm.db"


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

cgm_agent = Agent(
    model=gemini_model,
    instructions=dedent("""\
        You are a helpful assistant that extracts numerical CGM readings from user input.
        Only respond with the numeric value (mg/dL) of the glucose level.
        Do not explain or add any words — just return the number.
    """),
    add_datetime_to_instructions=False,
    markdown=False,
)

food_intake_agent = Agent(
    model=gemini_model,
    instructions=dedent("""\
        You are an assistant that helps log food intake.
        Extract the user's meal or snack description in a short phrase.
        Examples: "grilled chicken salad", "banana smoothie", "rice and dal"
        Respond only with the food description. No extra text.
    """),
    add_datetime_to_instructions=False,
    markdown=False,
)

meal_planner_agent = Agent(
    model=gemini_model,
    instructions=dedent("""\
        You are a smart diet assistant. Your job is to create adaptive meal plans to stabilize glucose levels.
        Consider the user’s:
        - Dietary preference (e.g. vegetarian, vegan, diabetic-friendly)
        - Medical conditions (e.g. Type 2 Diabetes, PCOS)
        - Last CGM readings (check if they are above or below the healthy range 80–300 mg/dL)

        Generate a plan with the next 3 meals (e.g., breakfast, lunch, dinner or snack), 
        using whole foods that help normalize glucose. 
        Include just food names, no recipes or explanations.

        Format:
        - Breakfast: <food>
        - Lunch: <food>
        - Dinner: <food>
    """),
    add_datetime_to_instructions=False,
    markdown=True,
)



# Function to fetch name from DB using user_id
def get_name_from_user_id(user_id):
    response = supabase.table("individuals").select("firstname, lastname").eq("user_id", user_id).execute()
    if response.data:
        return response.data[0]["firstname"], response.data[0]["lastname"]
    return None, None

def log_user_mood(user_id, user_input):
    try:
        response = mood_tracker_agent.run(user_input)
        mood = response.content.strip()

        result = supabase.table("moodlogs").insert({
            "user_id": user_id,
            "mood": mood,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }).execute()

        if not result.data:
            print(f"⚠️ Supabase insert error (MoodLogs): {result.error.message}")
        else:
            print(f"✅ Mood '{mood}' logged for user {user_id}")
    except Exception as e:
            print(f"⚠️ Failed to log mood: {e}")


def log_cgm_reading(user_id, user_input):
    try:
        response = cgm_agent.run(user_input)
        reading_str = response.content.strip()
        reading = int(reading_str)

        is_valid = 80 <= reading <= 300
        print(f"📈 CGM reading of {reading} mg/dL logged for user {user_id} — Valid: {is_valid}")

        # Insert into Supabase
        result = supabase.table("cgmreadings").insert({
            "user_id": user_id,
            "cgmvalue": reading,
            "recordedat": datetime.now(timezone.utc).isoformat()
        }).execute()

        if not result.data:
            print(f"⚠️ Supabase insert error: {result.error.message}")
        else:
            print("✅ CGM reading logged in Supabase.")

    except ValueError:
        print(f"❌ Could not convert response to number: '{response.content}'")
        
    except Exception as e:
        print(f"⚠️ Failed to log CGM reading: {e}")


def log_food_intake(user_id, user_input):
    try:
        response = food_intake_agent.run(user_input)
        food_data = response.content.strip()

        # Optional: Parse calories if included
        if ":" in food_data:
            food_item, calories = food_data.split(":", 1)
            calories = int(calories.strip())
        else:
            food_item = food_data
            calories = None

        result = supabase.table("foodintakelogs").insert({
            "user_id": user_id,
            "FoodItem": food_item.strip(),
            "Calories": calories,
            "RecordedAt": datetime.now(timezone.utc).isoformat()
        }).execute()

        if not result.data:
            print(f"⚠️ Supabase insert error (FoodIntake): {result.error.message}")
        else:
            print(f"✅ Food intake '{food_item}' logged for user {user_id}")
    except Exception as e:
        print(f"⚠️ Failed to log food intake: {e}")

def fetch_user_profile(user_id):
    try:
        response = supabase.table("individuals") \
            .select("dietarypreference", "medicalconditions") \
            .eq("user_id", user_id) \
            .single() \
            .execute()

        if not response.data:
            print(f"⚠️ Supabase error: {response.error.message}")
            return "", ""

        data = response.data
        return data.get("dietaryPreference", ""), data.get("medicalconditions", "")
    
    except Exception as e:
        print(f"⚠️ Error fetching user profile: {e}")
        return "", ""

def fetch_recent_cgm(user_id, limit=3):
    try:
        response = supabase.table("cgmreadings") \
            .select("cgmvalue") \
            .eq("user_id", user_id) \
            .order("recordedat", desc=True) \
            .limit(limit) \
            .execute()

        if not response.data:
            print("⚠️ No CGM readings found.")
            return []

        return [row["cgmvalue"] for row in response.data]
    except Exception as e:
        print(f"⚠️ Error fetching CGM readings: {e}")
        return []

def generate_meal_plan(user_id):
    diet_pref, medical_conditions = fetch_user_profile(user_id)
    recent_cgm = fetch_recent_cgm(user_id)

    prompt = f"""
    Dietary preference: {diet_pref}
    Medical conditions: {medical_conditions}
    Recent CGM readings: {recent_cgm}
    """

    try:
        response = meal_planner_agent.run(prompt)
        print("\n🍱 Adaptive Meal Plan:\n")
        print(response.content)
    except Exception as e:
        print(f"⚠️ Failed to generate meal plan: {e}")




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

    # Ask for CGM reading
    print("🤖: Please enter your latest glucose reading (mg/dL).")
    cgm_input = input("👤: ")

    # Log CGM reading
    log_cgm_reading(user_id, cgm_input)

    # Ask for food intake
    print("🤖: What did you eat today?")
    food_input = input("👤: ")

    # Log food
    log_food_intake(user_id, food_input)

    # Generate meal plan on request
    print("🤖: Would you like a personalized meal plan? (yes/no)")
    if input("👤: ").strip().lower() == "yes":
        generate_meal_plan(user_id)

if __name__ == "__main__":
    run_agent()
