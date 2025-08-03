import httpx
from agno.agent import Agent
from agno.tools import tool
from typing import Any, Callable, Dict
from agno.models.google import Gemini
from dotenv import load_dotenv
from textwrap import dedent
import os
from supabase import create_client, Client
from datetime import datetime, timezone, timedelta
import google.generativeai as genai
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.memory import Memory
from agno.storage.sqlite import SqliteStorage

# Load environment variables from .env file
load_dotenv()

# Access the API key
gemini_api_key = os.getenv("GEMINI_API_KEY")

url = os.getenv("SUPABASE_URL", "")
key = os.getenv("SUPABASE_KEY", "")
supabase = create_client(url, key)

# Create the Gemini model instance
gemini_model = Gemini(id="gemini-2.5-pro", api_key=gemini_api_key)


memory = Memory(
    model=gemini_model,
    db=SqliteMemoryDb(db_file="./data/user_memory1.db"),  # Local file
    delete_memories=False,
    clear_memories=False,
)
storage = SqliteStorage(table_name="agent_sessions", db_file="./data/user_memory1.db")


def serialize(data):
    serialized_value = ""
    for row in data:
        moodlog_string = f"Mood: {row['mood']}  Reasoning: {row['reasoning']} timestamp: {row['timestamp']}"
        serialized_value = serialized_value + moodlog_string + "\n"

    return serialized_value


@tool(
    name="end_conversation",  # Custom name for the tool (otherwise the function name is used)
    description="Used to end the conversation when the user requirements are fullfilled",  # Custom description (otherwise the function docstring is used)
    show_result=True,  # Show result after function call
    stop_after_tool_call=True,  # Return the result immediately after the tool call and stop the agent
    tool_hooks=[],  # Hook to run before and after execution
    requires_confirmation=False,  # Requires user confirmation before execution
)
def end_conversation() -> str:
    import sys

    sys.exit()
    return "program exitted"


@tool(
    name="mood_logger",  # Custom name for the tool (otherwise the function name is used)
    description="Used to log the mood and mood summary of the user, Always use this user shares about his feelings and emotions",  # Custom description (otherwise the function docstring is used)
    stop_after_tool_call=False,  # Return the result immediately after the tool call and stop the agent
    tool_hooks=[],  # Hook to run before and after execution
    requires_confirmation=False,  # Requires user confirmation before execution
)
def save_user_mood(mood: str, user_id: str, reasoning: str) -> str:
    """Use this to save the rolling mood average of the user"""
    now_utc = datetime.now(timezone.utc)
    start_of_day = datetime(
        now_utc.year, now_utc.month, now_utc.day, tzinfo=timezone.utc
    )
    end_of_day = start_of_day + timedelta(days=1)
    response = (
        supabase.table("moodlogs")
        .select("mood, reasoning,timestamp")
        .eq("user_id", user_id)
        .gte("timestamp", start_of_day)
        .lt("timestamp", end_of_day)
        .execute()
    )
    # print(response.data)
    if response.data:
        serialized_value = serialize(response.data)
        averageddata = callGemini(serialized_value, mood, reasoning)
        supabase.table("moodlogs").insert(
            {
                "user_id": user_id,
                "mood": mood,
                "reasoning": reasoning,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ).execute()
        upsert_today_record(
            "user_mood_summary",
            "updated_at",
            {
                "user_id": user_id,
                "mood_date": datetime.now(timezone.utc).isoformat(),
                "average_mood_score": int(
                    round(float(averageddata["average_mood_score"]))
                ),
                "mood_category": averageddata["mood_category"],
                "mood_reasoning": averageddata["mood_reasoning"],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            user_id,
        )
    else:
        supabase.table("moodlogs").insert(
            {
                "user_id": user_id,
                "mood": mood,
                "reasoning": reasoning,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ).execute()
        supabase.table("user_mood_summary").insert(
            {
                "user_id": user_id,
                "mood_date": datetime.now(timezone.utc).isoformat(),
                "average_mood_score": 0,
                "mood_category": mood,
                "mood_reasoning": reasoning,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ).execute()
    #     return response.data[0]["mood"], response.data[0]["reasoning"], respond.data[0]

    return "User mood log saved successfully. Provide a good solution to improve the mood if required"


def upsert_today_record(table: str, timestamp_column: str, data: dict, user_id: str):
    """
    Upsert a record into Supabase: find a record with today's timestamp (UTC), update if found, insert if not.

    :param table: The name of the Supabase table.
    :param timestamp_column: The timestamp column name (e.g., "created_at").
    :param data: The data to insert or update (must include the timestamp field).
    :return: The response data from Supabase.
    """
    # Calculate today's UTC start and end
    now_utc = datetime.now(timezone.utc)
    start_of_day = datetime(
        now_utc.year, now_utc.month, now_utc.day, tzinfo=timezone.utc
    )
    end_of_day = start_of_day + timedelta(days=1)

    # Check if a record for today exists
    query = (
        supabase.table(table)
        .select("*")
        .eq("user_id", user_id)
        .gte(timestamp_column, start_of_day.isoformat())
        .lt(timestamp_column, end_of_day.isoformat())
        .limit(1)
        .execute()
    )

    if query.data:
        # Record exists — update it using primary key (assumes 'id')
        record_id = query.data[0].get("id")
        if not record_id:
            raise Exception("Cannot update record: 'id' field is missing.")
        response = supabase.table(table).update(data).eq("id", record_id).execute()
        print("✅ Updated existing record")
    else:
        # No record for today — insert a new one
        response = supabase.table(table).insert(data).execute()
        print("➕ Inserted new record")

    return response.data


def callGemini(serialized_value, mood, reasoning):
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))  # type: ignore
    model = genai.GenerativeModel("gemini-2.5-flash")  # type: ignore

    system_prompt = f"""
   You are a expert mood log analyzer. You will be given with a a person's complete past mood logs(Today's logs) and present mood, along with the reasoning of why the user was in that particular mood. Your job is to identify the average mood of the person,mood score(Range 0-10) and overall reasoning.

    ##Output
    average_mood_score: <Cumulative mood score of the person ranging from 0-10>
    mood_category: <Overall mood of the person. max 2 words>
    mood_reasoning: <Cumulative reasoning of the person's mood>

    ##Input
    past_mood_logs:{serialized_value}
    current_mood:{mood}
    curent_mood_reasoning:{reasoning}

    """

    response = model.generate_content(system_prompt)
    output_dict = parse_output(response.text)

    return output_dict


import re


def parse_output(output):
    try:
        result = {}

        # Match keys and values
        pattern = r"(average_mood_score|mood_category|mood_reasoning):\s*(.+?)(?=\n(?:\w+_?\w*):|$)"

        matches = re.findall(pattern, output, re.IGNORECASE | re.DOTALL)

        for key, value in matches:
            result[key.lower()] = value.strip()

        # Validate required keys are present
        required_keys = {"average_mood_score", "mood_category", "mood_reasoning"}
        if required_keys.issubset(result.keys()):
            return result
        else:
            return {
                "average_mood_score": "NA",
                "mood_category": "NA",
                "mood_reasoning": "NA",
            }

    except Exception:
        return {
            "average_mood_score": "NA",
            "mood_category": "NA",
            "mood_reasoning": "NA",
        }


agent = Agent(
    model=gemini_model,
    memory=memory,
    enable_agentic_memory=True,
    enable_user_memories=True,
    storage=storage,
    add_history_to_messages=True,
    instructions=dedent(
        """\
        You are a warm and friendly assistant. Your job is to get the user_id and name then greet them personally. Check on the user's mood and build up a friendly conversation.
    """
    ),
    add_datetime_to_instructions=False,
    markdown=True,
    tools=[save_user_mood, end_conversation],
)
memory.clear()

agent.print_response("hai", stream=True, stream_intermediate_steps=True)

while True:
    prompt = input("user: ")
    agent.print_response(prompt, stream=True, stream_intermediate_steps=True)

# save_user_mood("Happy", "user_005", "Trying something new")
# agent = Agent(model=gemini_model, tools=[get_top_hackernews_stories])
# agent.print_response("Show me the top news from Hacker News")
