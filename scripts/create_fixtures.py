"""One-time script to create ingest test fixtures for P1.5 development."""
import json
import os

# Mary fixture: a lecture where the instructor uses 'mary' as an incidental variable name
# The old pipeline grabbed 'mary' as a question topic - this is the failing case
mary_fixture = {
    "id": "mary_test_fixture",
    "duration_seconds": 600.0,
    "video_url": "https://example.com/mary_lecture.mp4",
    "timing_config": {"min_trigger_gap": 15.0, "tolerance": 2.0},
    "transcript": [
        {"start_time": 0.0, "end_time": 30.0, "text": "Today we will look at Python functions."},
        {"start_time": 30.0, "end_time": 60.0,
         "text": "Let's say we have a function called greet. We pass it a name, and it prints hello. For example, greet('mary') prints hello mary."},
        {"start_time": 60.0, "end_time": 90.0,
         "text": "The parameter here is just a placeholder. It could be called anything."},
        {"start_time": 90.0, "end_time": 120.0,
         "text": "Now let us look at return values. A function can return a result instead of just printing."},
        {"start_time": 120.0, "end_time": 180.0,
         "text": "Using return, the function sends a value back to the caller. This is more flexible than print."},
        {"start_time": 180.0, "end_time": 240.0,
         "text": "You can assign the returned value to a variable and use it later."},
        {"start_time": 240.0, "end_time": 300.0,
         "text": "Default parameters let you define a fallback value. If the caller does not pass an argument, the default is used."},
        {"start_time": 300.0, "end_time": 360.0,
         "text": "Keyword arguments allow you to pass values by name rather than position, making calls more readable."},
        {"start_time": 360.0, "end_time": 420.0,
         "text": "Scope is about where a variable is visible. Variables inside a function are local by default."},
        {"start_time": 420.0, "end_time": 480.0,
         "text": "The global keyword lets a function modify a variable defined outside. Use it sparingly."},
        {"start_time": 480.0, "end_time": 540.0,
         "text": "Lambda expressions create small anonymous functions inline, useful for short callbacks."},
        {"start_time": 540.0, "end_time": 600.0,
         "text": "That covers the basics of functions in Python. Practice by writing your own."},
    ],
    "interventions": [],
    "recall_pool": [],
}

# Baseline: the BAD checkpoints the old (generator_version 1) pipeline produced
# These represent the class of failures P1.5 must eliminate
mary_baseline = {
    "generator_version": 1,
    "note": "Bad checkpoints from transcript-direct generation. P1.5.1 must reject all of these.",
    "checkpoints": [
        {
            "id": "bad_1",
            "question": "Which of the following was mentioned in the lecture?",
            "options": ["mary", "greet", "hello", "print"],
            "correct_answer": "mary",
            "concept": "example variable name",
            "failure_reason": "banned_stem: 'mentioned in the lecture' + incidental_detail",
        },
        {
            "id": "bad_2",
            "question": "According to the instructor, what name was used in the greet example?",
            "options": ["mary", "alice", "bob", "jane"],
            "correct_answer": "mary",
            "concept": "example variable name",
            "failure_reason": "banned_stem: 'according to the instructor' + incidental_detail",
        },
        {
            "id": "bad_3",
            "question": "What did the instructor say was printed when greet was called?",
            "options": ["hello mary", "goodbye mary", "hi mary", "hey mary"],
            "correct_answer": "hello mary",
            "concept": "print output of illustrative example",
            "failure_reason": "banned_stem: 'instructor say' + tests incidental illustration value",
        },
    ],
}

# Linux fixture: control case (strong narration, should produce good checkpoints)
# Each segment is 30s to match the window size for clean density measurement
linux_fixture = {
    "id": "linux_control_fixture",
    "duration_seconds": 480.0,
    "video_url": "https://example.com/linux_lecture.mp4",
    "timing_config": {"min_trigger_gap": 15.0, "tolerance": 2.0},
    "transcript": [
        {"start_time": 0.0, "end_time": 30.0,
         "text": "The Linux file system is a hierarchical tree rooted at the forward slash directory containing every file and directory on the system including devices configuration and user home directories."},
        {"start_time": 30.0, "end_time": 60.0,
         "text": "The ls command lists directory contents and with the hyphen la flag shows all files including hidden dot files along with their permissions owner group size and modification time."},
        {"start_time": 60.0, "end_time": 90.0,
         "text": "File permissions appear as a ten character string the first character shows the file type a dash for regular file and the letter d for a directory entry in the filesystem."},
        {"start_time": 90.0, "end_time": 120.0,
         "text": "The next nine characters form three groups of three representing read write and execute permissions for three classes of user the owner the group members and everyone else."},
        {"start_time": 120.0, "end_time": 150.0,
         "text": "chmod changes permissions using symbolic mode like chmod u plus x to add execute permission for the owner or numeric octal mode like chmod 755 to set all three classes at once."},
        {"start_time": 150.0, "end_time": 180.0,
         "text": "In octal mode each digit is a sum of four for read two for write and one for execute so 755 means rwx for owner and rx for group and others."},
        {"start_time": 180.0, "end_time": 210.0,
         "text": "The pipe operator represented by a vertical bar character connects two commands so the standard output of the left command becomes the standard input of the right command."},
        {"start_time": 210.0, "end_time": 240.0,
         "text": "grep filters lines from its input that match a given pattern and when combined with pipes allows you to search and filter the output of any command efficiently."},
        {"start_time": 240.0, "end_time": 270.0,
         "text": "Redirection operators change where output goes the single greater than sign redirects standard output to a file and overwrites any existing content in that file."},
        {"start_time": 270.0, "end_time": 300.0,
         "text": "Two greater than signs append output to a file without overwriting existing content and the less than sign redirects a file as standard input to a command."},
        {"start_time": 300.0, "end_time": 330.0,
         "text": "Understanding pipes and redirection together lets you build command pipelines combining grep sort uniq cut and other tools to process data entirely from the command line."},
        {"start_time": 330.0, "end_time": 360.0,
         "text": "Shell scripting captures these pipelines in reusable scripts with variables loops and conditionals making automation and batch processing straightforward on any Linux system."},
        {"start_time": 360.0, "end_time": 390.0,
         "text": "Environment variables store configuration values that shell commands and scripts can read the PATH variable for example lists directories the shell searches for executable files."},
        {"start_time": 390.0, "end_time": 420.0,
         "text": "Process management commands like ps show running processes and kill sends signals to terminate or pause them while top provides a real time view of resource usage."},
        {"start_time": 420.0, "end_time": 450.0,
         "text": "Combining all these tools with man pages for documentation and tab completion for discovery makes the Linux command line a powerful environment for professional developers and administrators."},
        {"start_time": 450.0, "end_time": 480.0,
         "text": "Practice these fundamentals by writing small scripts that use pipes redirection and permission management and your confidence on the command line will grow quickly."},
    ],
}

os.makedirs("tests/fixtures/ingest", exist_ok=True)
with open("tests/fixtures/ingest/mary_transcript.json", "w") as f:
    json.dump(mary_fixture, f, indent=2)
with open("tests/fixtures/ingest/mary_baseline.json", "w") as f:
    json.dump(mary_baseline, f, indent=2)
with open("tests/fixtures/ingest/linux_transcript.json", "w") as f:
    json.dump(linux_fixture, f, indent=2)

print("Fixtures written:")
print("  tests/fixtures/ingest/mary_transcript.json")
print("  tests/fixtures/ingest/mary_baseline.json")
print("  tests/fixtures/ingest/linux_transcript.json")
