from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
import os
from openai import OpenAI
from dotenv import load_dotenv
import random
from datetime import datetime  # For tracking user activity timestamps

# Load environment variables from a .env file
load_dotenv("app.env")

# Initialize the OpenAI client with your API key
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
)

# Initialize the Flask app
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///gamification.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Comprehensive persona for Cikgu Bot with a syllabus framework
persona = (
    "You are a friendly and knowledgeable assistant named 'Cikgu Bot'. You help Year 6 primary school students "
    "learn about Science in a fun and easy-to-understand way. You are familiar with the Malaysian Year 6 Science syllabus, "
    "which includes topics such as:\n"
    "- Scientific Process Skills: observation, classification, measurement, inference, prediction, communication, controlling variables.\n"
    "- Physical Science: understanding forces, speed, and air pressure.\n"
    "- Life Science: human body systems, microorganisms, and interactions among living things.\n"
    "- Materials Science: food preservation, waste management, and conservation.\n"
    "- Earth and Space Science: eclipses, galaxies, and the solar system.\n"
    "- Technology and Engineering: structure stability, and the impact of technology on daily life.\n"
    "When you answer questions, use simple language that is easy for young students to understand. Always be patient, "
    "and if you don’t know the answer, say, 'Hmm, I'm not sure about that, but I can help you find out!'"
)

# Define User Model for Gamification Tracking
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    points = db.Column(db.Integer, default=0)
    stickers = db.Column(db.Text)  # Store stickers as comma-separated values
    # Enhanced tracking fields
    questions_asked = db.Column(db.Integer, default=0)  # Count total questions
    quizzes_completed = db.Column(db.Integer, default=0)  # Count quiz attempts
    correct_answers = db.Column(db.Integer, default=0)  # Count correct answers
    last_active = db.Column(db.String(50))  # Last activity timestamp

# Create the database tables
with app.app_context():
    db.create_all()

# Conversation history to maintain context
conversation_history = []

# Flask route for the main page
@app.route("/")
def home():
    return render_template("index_CikguBot.html")

# Function to generate a response for the chatbot
def generate_response(user_input, username):
    global conversation_history
    conversation_history.append({"role": "user", "content": user_input})
    messages = [{"role": "system", "content": persona}] + conversation_history

    # Using the OpenAI client to create chat completions
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=messages,
        max_tokens=150,
        temperature=0.7,
    )

    bot_response = response.choices[0].message.content.strip()
    conversation_history.append({"role": "assistant", "content": bot_response})

    # Limit the conversation history to avoid excessive context length
    if len(conversation_history) > 6:
        conversation_history = conversation_history[-6:]

    # Reward users for asking questions
    user = User.query.filter_by(username=username).first()
    if user:
        user.points += 10  # Add 10 points for every interaction
        user.questions_asked += 1  # Track question count
        user.last_active = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # Update timestamp
        db.session.commit()

    return bot_response

# Flask route for the chatbot API
@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_input = data.get("message", "")
    username = data.get("username", "guest")

    # Create user if not exists
    user = User.query.filter_by(username=username).first()
    if not user:
        user = User(username=username)
        db.session.add(user)
        db.session.commit()

    response_text = generate_response(user_input, username)

    # Return a response that includes the user's current points and stickers
    user = User.query.filter_by(username=username).first()
    return jsonify({"response": response_text, "points": user.points, "stickers": user.stickers})

# Flask route for dynamic quiz generation
@app.route("/generate_quiz", methods=["POST"])
def generate_quiz():
    data = request.json
    topic = data.get("topic", "general science")

    # Generate quiz question using OpenAI API
    prompt = f"Create a multiple-choice science quiz question for Year 6 students about {topic}. Include 4 answer options and indicate the correct answer."
    
    # Error handling for API calls
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.7,
        )
    except Exception as e:
        print(f"Error generating quiz: {e}")
        return jsonify({"error": "Failed to generate quiz. Please try again."}), 500

    quiz_content = response.choices[0].message.content.strip()

    # Debug print to see the entire response content
    print("Quiz Content:", quiz_content)

    # Parse the generated question and answers
    lines = quiz_content.split("\n")
    question = lines[0]
    choices = []
    correct_answer = ""

    # Look for choices and detect the correct answer line
    for line in lines[1:]:
        line = line.strip()
        if line.lower().startswith("correct answer:") or line.lower().startswith("answer:"):
            correct_answer = line.split(":")[-1].strip()  # Extract text after "Correct answer:" or "Answer:"
        elif line and line[0] in "ABCD" and line[1:3] == ") ":  # Ensuring it's a choice like "A) Option"
            choices.append(line)

    # If `correct_answer` is empty, log a warning
    if not correct_answer:
        print("Warning: No correct answer detected in the response")
    else:
        print("Parsed Correct Answer:", correct_answer)

    # Debug print to verify choices
    print("Parsed Choices:", choices)

    # Send the response to the frontend without shuffling
    return jsonify({
        "question": question,
        "choices": choices[:4],  # Ensure we only send four choices
        "correct_answer": correct_answer
    })



# Flask route to submit quiz answer
@app.route("/quiz_answer", methods=["POST"])
def quiz_answer():
    data = request.json
    user_answer = data.get("answer", "").strip()
    correct_answer = data.get("correct_answer", "").strip()
    username = data.get("username", "guest")  # Support multiple users

    # Normalize both `user_answer` and `correct_answer` by removing labels
    user_answer_clean = user_answer.split(" ", 1)[-1].strip()  # Remove label if present
    correct_answer_clean = correct_answer.split(" ", 1)[-1].strip()  # Remove label if present

    # Retrieve user from database
    user = User.query.filter_by(username=username).first()

    # Check if the user's answer is correct
    if user_answer_clean.lower() == correct_answer_clean.lower():  # Case-insensitive comparison
        # Correct answer, award points and a sticker
        if user:
            user.points += 20  # Reward extra points for correct answer
            user.correct_answers += 1  # Track correct answers
            user.quizzes_completed += 1  # Track quiz attempts
            user.last_active = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # Update timestamp
            
            # Milestone-based sticker rewards
            stickers = user.stickers.split(',') if user.stickers else []
            if user.correct_answers % 10 == 0:
                stickers.append("🏆")  # Trophy every 10 correct
            elif user.correct_answers % 5 == 0:
                stickers.append("🌟")  # Special star every 5 correct
            else:
                stickers.append("⭐️")  # Regular star
            user.stickers = ','.join(stickers)
            db.session.commit()

        return jsonify({"message": "Correct! You've earned 20 points and a sticker!", "points": user.points,
                        "stickers": user.stickers, "correct_answers": user.correct_answers})
    
    # Track wrong answers
    if user:
        user.quizzes_completed += 1
        user.last_active = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.session.commit()

    return jsonify({"message": "Oops, that's not correct. Try again!", "points": user.points})


# Flask route to clear conversation history if needed
@app.route("/clear", methods=["POST"])
def clear_history():
    global conversation_history
    conversation_history = []
    return jsonify({"message": "Conversation history cleared."})

# Get user statistics - Usage: GET /user_stats?username=guest
@app.route("/user_stats", methods=["GET"])
def user_stats():
    username = request.args.get("username", "guest")
    user = User.query.filter_by(username=username).first()
    
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    return jsonify({
        "username": user.username,
        "points": user.points,
        "questions_asked": user.questions_asked,
        "quizzes_completed": user.quizzes_completed,
        "correct_answers": user.correct_answers,
        "accuracy": round((user.correct_answers / user.quizzes_completed * 100), 1) if user.quizzes_completed > 0 else 0,
        "stickers": user.stickers,
        "last_active": user.last_active
    })

# Get leaderboard - Usage: GET /leaderboard?limit=10
@app.route("/leaderboard", methods=["GET"])
def leaderboard():
    limit = request.args.get("limit", 10, type=int)
    top_users = User.query.order_by(User.points.desc()).limit(limit).all()
    
    leaderboard_data = []
    for rank, user in enumerate(top_users, start=1):
        leaderboard_data.append({
            "rank": rank,
            "username": user.username,
            "points": user.points,
            "correct_answers": user.correct_answers,
            "stickers": user.stickers
        })
    
    return jsonify({"leaderboard": leaderboard_data})

# Get user achievements - Usage: GET /achievements?username=guest
@app.route("/achievements", methods=["GET"])
def achievements():
    username = request.args.get("username", "guest")
    user = User.query.filter_by(username=username).first()
    
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    achievements_list = []
    
    # Question-based achievements
    if user.questions_asked >= 10:
        achievements_list.append({"name": "Curious Mind", "description": "Asked 10+ questions", "icon": "🧠"})
    if user.questions_asked >= 50:
        achievements_list.append({"name": "Super Curious", "description": "Asked 50+ questions", "icon": "🤔"})
    
    # Quiz performance achievements
    if user.correct_answers >= 5:
        achievements_list.append({"name": "Quiz Novice", "description": "5 correct answers", "icon": "📝"})
    if user.correct_answers >= 20:
        achievements_list.append({"name": "Quiz Master", "description": "20 correct answers", "icon": "🎓"})
    if user.correct_answers >= 50:
        achievements_list.append({"name": "Science Genius", "description": "50 correct answers", "icon": "🔬"})
    
    # Points-based achievements
    if user.points >= 100:
        achievements_list.append({"name": "Point Collector", "description": "Earned 100+ points", "icon": "💯"})
    if user.points >= 500:
        achievements_list.append({"name": "Point Master", "description": "Earned 500+ points", "icon": "💎"})
    
    # Accuracy achievement
    accuracy = round((user.correct_answers / user.quizzes_completed * 100), 1) if user.quizzes_completed > 0 else 0
    if accuracy >= 80 and user.quizzes_completed >= 10:
        achievements_list.append({"name": "Accuracy Expert", "description": "80%+ accuracy on 10+ quizzes", "icon": "🎯"})
    
    return jsonify({"achievements": achievements_list, "total": len(achievements_list)})

def reset_user_points():
    with app.app_context():
        users = User.query.all()
        for user in users:
            user.points = 0
            user.stickers = ""
        db.session.commit()


if __name__ == "__main__":
    # Removed auto-reset to preserve user progress
    # Uncomment to reset: reset_user_points()
    app.run(debug=True)
