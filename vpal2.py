#!/usr/bin/env python3

from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters, JobQueue
from openai import AsyncOpenAI, OpenAI
from pathlib import Path
import asyncio
import datetime
import shutil
import random
import json
import signal
import os
import time
import requests

# OpenAI API key and Telegram bot token
openai_api_key = 'API_KEY_HERE'
telegram_bot_token = 'BOT_TOKEN_HERE'

telegramVoiceURL=f"https://api.telegram.org/bot{telegram_bot_token}/sendVoice" # for TTS voice notes

# Instantiating OpenAI client
client = AsyncOpenAI(api_key=openai_api_key)
audioClient= OpenAI(api_key=openai_api_key)

# Reading user profile
def read_profile():
    try:
        with open('profile.txt', 'r') as file:
            return file.read()
    except FileNotFoundError:
        return ""

profile_content = read_profile()

# Generating a profile message
profile_message = {"role": "system", "content": profile_content}

# Last interaction timestapm
last_interaction_time = None
conversation_history = [profile_message]
message_queue = []
timer_task = None
inactivity_task = None
shutdown_event = asyncio.Event()

# Parsing past conversation history
def read_summaries(file_path='{articlesSummariesPath}'):
    try:
        with open(file_path, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        return []

async def respond_to_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global last_interaction_time
    global message_queue
    global timer_task
    global inactivity_task

    print("Received message:", update.message.text)  # Debugging print
    user_message = update.message.text

    # Preshot server reboots with permanent interaction timestamp storage
    last_interaction_time = datetime.datetime.now()
    with open("timestamp.txt", "w") as f:
        f.write(str(last_interaction_time))

    # Message queue
    message_queue.append({"role": "user", "content": user_message})

    if timer_task:
        timer_task.cancel()

    if inactivity_task:
        inactivity_task.cancel()

    # Delay reply by {range} in seconds to mimick human reaction time and allow for messaging queue to form
    delay = random.randint(90 , 180)  # in seconds
    timer_task = asyncio.create_task(wait_and_send_messages(context, update, delay))

    #Start a new inactivity task
    inactivity_task = asyncio.create_task(check_inactivity(context, update.effective_chat.id))


def pinginternet():
    #host="www.nonexistentdomain.com"
    #host="www.google.com"
    host="platform.openai.com"
    status=(os.system(f"ping -c 2 {host} >/dev/null 2>&1"))
    if status==0:
        return True
    else:
        return False

def audiotts(x: str):
    shutil.copyfile("./voiceNotes/note.ogg","./voiceNotes/note_Old.ogg")
    speech_file_path= Path(__file__).parent / "./voiceNotes/note.ogg"
    response = audioClient.audio.speech.create (model="tts-1", voice="onyx", response_format="opus", input=x)
    response.stream_to_file(speech_file_path)


async def wait_and_send_messages(context: ContextTypes.DEFAULT_TYPE, update: Update, delay: int) -> None:
    global message_queue
    global conversation_history
    global timer_task

    try:
        # Wait for the specified delay
        await asyncio.sleep(delay)

        # Merge all messages in the queue
        merged_message_content = " ".join([msg["content"] for msg in message_queue])
        merged_message = {"role": "user", "content": merged_message_content}
        
        promptContext="[Requirement: You are a friend to the user. Their first language is french and they are learning english. Additional information regarding them is within the context they give you and the conversation history. Respond using conversational length sentences, a simpler vocabulary, and an informal, young adult tone]"
        # Create a list of messages including the context and the merged message
        requirementText={"role": "system", "content": promptContext}
        messages = [requirementText] + conversation_history + [merged_message]

        while not pinginternet():
            print("No responses from host URL/n")
            time.sleep(300)

        # Push messages to OpenAI's ChatGPT and pull response
        try:
            chatgpt_response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages
            )
            print("API Response:", chatgpt_response)  # Debugging print
        except Exception as e:
            print("Error during API call:", str(e))  # Print errors from API call
            timer_task = None
            return
        response_text = chatgpt_response.choices[0].message.content

        # Save in response history
        conversation_history.append({"role": "assistant", "content": response_text})

        print("Sending response:", response_text)  # Debugging print
        
        while not pinginternet():
            print("No responses from host url/n")
            time.sleep(300)

        rando=round(random.random(), 1)
        print(f"random text/speech value is {rando}")
        if (rando>=0.4):
            # Push response to Telegram user
            await context.bot.send_message(chat_id=update.effective_chat.id, text=response_text)
        elif rando<0.4:
            audiotts(response_text)
            pathtoVoice="{voiceNoteDirectoryPath}/note.ogg"
            print(f"path is currently {pathtoVoice}")
            payload = {
                    "voice": pathtoVoice,
                    "duration": None,
                    "disable_notification": False,
                    "reply_to_message_id": None
                     }
            headers = {
                    "accept": "application/json",
                    "User-Agent": "Telegram Bot SDK - (https://github.com/irazasyed/telegram-bot-sdk)",
                    "content-type": "application/json"
                    }
            #response = requests.post(telegramVoiceURL, json=payload, headers=headers)
            await context.bot.sendVoice(chat_id=update.effective_chat.id, voice=pathtoVoice)
        else:
            print("Unexpected voice/text randomization value")

        # Profile update
        await update_profile()

        # Reset the timer task
        message_queue = []
        timer_task = None
    except asyncio.CancelledError:
        print("wait_and_send_messages task was cancelled")
    except Exception as e:
        print(f"Unexpected error in wait_and_send_messages: {e}")

async def update_profile() -> None:
    global conversation_history

    try:
        # Reading profile content
        profile_content = read_profile()

        # Create a message to update the profile
        messages = conversation_history + [
            {"role": "system", "content": "Strictly reply by updating this profile with the information you currently have about me. Do not add anything else to your reply."},
            {"role": "user", "content": profile_content}
        ]

        # Send the messages to OpenAI's ChatGPT and get the updated profile
        try:
            profile_update_response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages
            )
            updated_profile = profile_update_response.choices[0].message.content
            print("Updated Profile:", updated_profile)  # Debugging print
            
            # profile backup
            shutil.copyfile('profile.txt', 'profileBak.txt')

            # Update profile
            with open('profile.txt', 'w') as file:
                file.write(updated_profile)

            # Reset the profile message with the new content
            profile_message["content"] = updated_profile
        except Exception as e:
            print("Error during profile update request:", str(e))
        # Print errors from API call
        except asyncio.CancelledError:
            print("update_profile task was cancelled")
    except Exception as e:
        print(f"Unexpected error in update_profile: {e}")

async def check_inactivity(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    global last_interaction_time
    global conversation_history

    try:
        while True:
            print(f"Checking inactivity at {datetime.datetime.now()}")

            await asyncio.sleep(43200)  # Check every 12 hour and messages user if inactive for too long
            with open("timestamp.txt","r") as f:
                print("testing timestamp reading")
                lastTime=f.read()
                parsedTime= datetime.datetime.fromisoformat(lastTime)
            timeDiff=datetime.datetime.now()-parsedTime

#            if last_interaction_time and (datetime.datetime.now() - last_interaction_time).total_seconds() >= 36 * 3600: # Sends a message back every 36 hours
            if timeDiff>=datetime.timedelta(days=1, hours=12, minutes=0, seconds=0):
                print("Inactivity detected, preparing to send a message...")

                # Read summaries
                summaries = read_summaries()

                # Choose a random summary if available
                if summaries:
                    summary = random.choice(summaries)
                    summary_content = f"Title: {summary['title']}\nSummary: {summary['summary']}"
                    inactivity_message = {"role": "user", "content": f"Initiate a conversation based on the following article: {summary_content}"}
                else:
                    inactivity_message = {"role": "user", "content": "Initiate a conversation on either my job, the way my day is going, or any interesting thing I have been doing recently."}

                conversation_history.append(inactivity_message)

                # Send the inactivity message to OpenAI's ChatGPT and get the response
                try:
                    chatgpt_response = await client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=conversation_history
                    )
                    print("API Response (Inactivity):", chatgpt_response)  # Debugging print
                except Exception as e:
                    print("Error during API call (Inactivity):", str(e))
                    return

                # Access the content of the message attribute correctly
                response_text = chatgpt_response.choices[0].message.content
                print(f"Received response from ChatGPT: {response_text}")

                # Append ChatGPT's response to the conversation history
                conversation_history.append({"role": "assistant", "content": response_text})

                # Send the response to the user on Telegram using the passed chat_id
                try:
                    await context.bot.send_message(chat_id=chat_id, text=response_text)
                    print("Sent response to Telegram.")
                except Exception as e:
                    print(f"Failed to send message on Telegram: {e}")

                # Reset the last interaction time
                last_interaction_time = datetime.datetime.now()
                print(f"Reset last interaction time to: {last_interaction_time}")

    except asyncio.CancelledError:
        print("check_inactivity task was cancelled")
    except Exception as e:
        print(f"Unexpected error in check_inactivity: {e}")



async def shutdown():
    global timer_task, inactivity_task
    print("Shutting down...")
    shutdown_event.set()

    # Cancel tasks
    if timer_task:
        timer_task.cancel()
    if inactivity_task:
        inactivity_task.cancel()

    # Wait for tasks to finish
    if timer_task:
        await timer_task
    if inactivity_task:
        await inactivity_task

    print("Shutdown complete")

def signal_handler(sig, frame):
    asyncio.get_event_loop().create_task(shutdown())

if __name__ == '__main__':
    print("Bot is starting...")  # Debugging print

    # Added for for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Initialize the bot with appropriate Telegram Bot Token
    application = Application.builder().token(telegram_bot_token).build()

    # Text message handler
    text_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), respond_to_text)
    application.add_handler(text_handler)

    # Initialize the JobQueue and schedule the context update every 12 hours
    job_queue = JobQueue()
    job_queue.set_application(application)
    job_queue.run_repeating(update_profile, interval=43200, first=43200)

    # Start the bot and run it until manually stopped
    application.run_polling()
    
    # Handle graceful shutdown
    asyncio.run(shutdown())

    # Commented out the terminal interface run command
    # asyncio.run(terminal_interface())
