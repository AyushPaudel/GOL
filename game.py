from flask import Flask, jsonify, request, session, render_template
from flask_cors import CORS
from dotenv import load_dotenv
import os
import sqlite3
import json
from langchain.llms import OpenAI
from langchain.prompts import PromptTemplate

app = Flask(__name__)
CORS(app)
app.secret_key = os.urandom(24)


class ModernWesterosGame:
    def __init__(self):
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OpenAI API key not found in environment variables")

        self.llm = OpenAI(temperature=0.8)
        self.player_history = []
        self.happiness = 30  # Starting happiness
        self.wealth = 100000  # Starting wealth
        self.turn_count = 0
        self.game_id = os.urandom(16).hex()

        self.setup_templates()
        self.setup_database()

    def get_serializable_state(self):
        """Return a JSON-serializable state of the game."""
        return {
            "player_history": self.player_history,
            "happiness": self.happiness,
            "wealth": self.wealth,
            "turn_count": self.turn_count,
            "game_id": self.game_id,
        }

    def load_state(self, state):
        """Load game state from a dictionary."""
        self.player_history = state["player_history"]
        self.happiness = state["happiness"]
        self.wealth = state["wealth"]
        self.turn_count = state["turn_count"]
        self.game_id = state["game_id"]

    def setup_database(self):
        conn = sqlite3.connect("westeros_realty.db")
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS choices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                choice_text TEXT NOT NULL,
                game_id TEXT NOT NULL
            )
        """
        )
        conn.commit()
        conn.close()

    def setup_templates(self):
        self.story_template = PromptTemplate(
            input_variables=[
                "history",
                "current_situation",
                "happiness",
                "wealth",
                "previous_choices",
            ],
            template=(
                "You are a witty narrator in a world where Jon Snow has traded his Night's Watch cloak for a realtor's suit. "
                "Mix modern real estate scenarios with Game of Thrones references and humor.\n\n"
                "Jon's Current Status:\n"
                "Happiness: {happiness}/100\n"
                "Wealth: ${wealth}\n\n"
                "Previous choices in this game: {history}\n"
                "Previously used choices in database: {previous_choices}\n"
                "Current situation: {current_situation}\n\n"
                "Generate a short story segment (2-3 sentences) with Game of Thrones references.\n"
                "Then provide 3 UNIQUE choices that are witty and concise (max 15 words each).\n"
                "Use GOT-style humor and puns in the choices. Each choice must have exact numerical impacts in parentheses.\n\n"
                "Format your response as follows:\n"
                "STORY: [Your story text here]\n"
                "CHOICES:\n"
                "1. Act like a Dothraki: Take what is yours with fire and blood (Happiness: +20, Wealth: -50000)\n"
                "2. Consult with Bran: See the future and make wise investments (Happiness: +10, Wealth: +25000)\n"
                "3. Meet with the Iron Bank: Get a loan and rule the market (Happiness: -15, Wealth: +40000)\n\n"
                "IMPORTANT FORMAT RULES:\n"
                "- Do not use square brackets []\n"
                "- Never use +/- together\n"
                "- Always specify a sign (+ or -) for every number\n"
                "- No spaces in numbers\n"
                "- Keep exact order: Happiness, Wealth\n"
            ),
        )

        self.consequence_template = PromptTemplate(
            input_variables=["history", "choice", "happiness", "wealth"],
            template=(
                "Based on Jon's history: {history}\n"
                "Current status:\n"
                "Happiness: {happiness}/100\n"
                "Wealth: ${wealth}\n"
                "They chose: {choice}\n\n"
                "Generate a consequence (2-3 sentences) that blends modern real estate outcomes with Game of Thrones references.\n"
                "Be creative and humorous while keeping the real estate aspects realistic."
            ),
        )

        self.story_chain = self.story_template | self.llm
        self.consequence_chain = self.consequence_template | self.llm

    def store_choice(self, choice_text):
        conn = sqlite3.connect("westeros_realty.db")
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO choices (choice_text, game_id) VALUES (?, ?)",
            (choice_text, self.game_id),
        )
        conn.commit()
        conn.close()

    def get_previous_choices(self):
        conn = sqlite3.connect("westeros_realty.db")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT choice_text FROM choices WHERE game_id = ?", (self.game_id,)
        )
        choices = [row[0] for row in cursor.fetchall()]
        conn.close()
        return choices

    def format_history(self):
        return (
            "No previous choices."
            if not self.player_history
            else " Then ".join(self.player_history)
        )

    def parse_stats_impact(self, choice):
        try:
            if "(" not in choice or ")" not in choice:
                return 0, 0

            impacts = choice.split("(")[1].split(")")[0].split(",")
            if len(impacts) < 2:
                return 0, 0

            def extract_number(impact_str):
                return int("".join(c for c in impact_str if c.isdigit() or c in "+-"))

            happiness_impact = extract_number(impacts[0])
            wealth_impact = extract_number(impacts[1])

            return happiness_impact, wealth_impact

        except Exception as e:
            print(f"Error parsing choice impacts: {e}")
            return 0, 0

    def update_stats(self, choice_text):
        happiness_impact, wealth_impact = self.parse_stats_impact(choice_text)
        self.happiness = max(0, min(100, self.happiness + happiness_impact))
        self.wealth = max(0, self.wealth + wealth_impact)
        return happiness_impact, wealth_impact

    def check_game_over(self):
        if self.happiness <= 0:
            return (
                True,
                "Game Over! Your happiness has reached zero. The night is dark and full of terrors.",
            )
        if self.wealth <= 0:
            return (
                True,
                "Game Over! You've gone broke. Even the Iron Bank won't help you now.",
            )
        if self.happiness >= 80 and self.wealth >= 150000:
            return (
                True,
                "Victory! You've achieved both wealth and happiness. The North remembers your success!",
            )
        if self.turn_count >= 10:
            return (
                True,
                "Game Over! You've completed your journey, but haven't reached greatness.",
            )
        return False, ""

    def start_game(self):
        initial_situation = (
            "Jon Snow, having left the Night's Watch for a new life in modern-day real estate, "
            "stands before the gleaming Glass Tower in downtown King's Landing (formerly Manhattan). "
            "His father's words echo in his head: 'Winter is Coming... and so is the housing market crash.'"
        )
        return self.get_story_segment(initial_situation)

    def get_story_segment(self, current_situation):
        try:
            previous_choices = self.get_previous_choices()
            response = self.story_chain.invoke(
                {
                    "history": self.format_history(),
                    "current_situation": current_situation,
                    "happiness": self.happiness,
                    "wealth": self.wealth,
                    "previous_choices": json.dumps(previous_choices),
                }
            )
            return response

        except Exception as e:
            print(f"Error generating story segment: {e}")
            return "Error generating story segment."

    def make_choice(self, choice_text):
        try:
            self.turn_count += 1
            if not choice_text or len(choice_text.strip()) == 0:
                raise ValueError("Empty choice text")

            self.store_choice(choice_text)
            self.update_stats(choice_text)

            consequence_response = self.consequence_chain.invoke(
                {
                    "history": self.format_history(),
                    "choice": choice_text,
                    "happiness": self.happiness,
                    "wealth": self.wealth,
                }
            )

            consequence = consequence_response
            self.player_history.append(choice_text)

            return consequence, self.get_story_segment(consequence)

        except Exception as e:
            print(f"Error processing choice: {e}")
            return "The outcome of your choice was unclear...", self.get_story_segment(
                "Jon needs to reassess his options..."
            )


@app.route("/api/game", methods=["POST"])
def game_action():
    try:
        data = request.get_json() or {}
        choice = data.get("choice")

        # If no choice provided or no existing game, start new game
        if not choice or "game_state" not in session:
            game = ModernWesterosGame()
            current_segment = game.start_game()

            session["game_state"] = game.get_serializable_state()
            session["current_segment"] = current_segment

            return jsonify(
                {
                    "status": "success",
                    "game_state": {
                        "turn": game.turn_count + 1,
                        "happiness": game.happiness,
                        "wealth": game.wealth,
                        "story": current_segment.split("STORY:")[1]
                        .split("CHOICES:")[0]
                        .strip(),
                        "choices": [
                            choice.strip()
                            for choice in current_segment.split("CHOICES:\n")[1].split(
                                "\n"
                            )
                            if choice.strip()
                        ][:3],
                    },
                }
            )

        # Process choice for existing game
        if choice not in ["1", "2", "3"]:
            return jsonify({"status": "error", "message": "Invalid choice"}), 400

        game = ModernWesterosGame()
        game.load_state(session["game_state"])
        current_segment = session["current_segment"]

        choices = current_segment.split("CHOICES:\n")[1].split("\n")
        chosen_action = choices[int(choice) - 1].lstrip("123. ")

        consequence, next_segment = game.make_choice(chosen_action)

        session["game_state"] = game.get_serializable_state()
        session["current_segment"] = next_segment

        is_game_over, message = game.check_game_over()

        response = {
            "status": "success",
            "game_state": {
                "turn": game.turn_count + 1,
                "happiness": game.happiness,
                "wealth": game.wealth,
                "consequence": consequence,
                "story": next_segment.split("STORY:")[1].split("CHOICES:")[0].strip(),
                "choices": [
                    choice.strip()
                    for choice in next_segment.split("CHOICES:\n")[1].split("\n")
                    if choice.strip()
                ][:3],
                "is_game_over": is_game_over,
                "game_over_message": message if is_game_over else None,
            },
        }

        return jsonify(response)

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/reset", methods=["POST"])
def reset_game():
    session.clear()
    return jsonify({"status": "success", "message": "Game reset successfully"})


@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    app.run()
