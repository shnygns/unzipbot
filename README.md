# Unzip Bot
### Authored by Shinanygans (shinanygans@proton.me)

This bot will unzip archive files that are posted to it.

## Prerequisites

Before you begin, ensure you have met the following requirements:

- **Python 3.10 or higher**: If you don't have Python installed, you can download it from the [official Python website](https://www.python.org/downloads/).

## Installation

Follow these steps to set up your project:

1. Clone this repository to your local machine (CLONE IT TO THE SAME AREA WHERE YOU PUT YOUR SHIN LOUNGES!):

    ```shell
    git clone https://github.com/shnygns/unzipbot.git
    ```

2. VERY IMPORTANT - YOU MUST INSTALL UNRAR TO YOUR SERVER

    ```shell
    sudo apt install unrar
    ```

    IF YOU DO NOT DO THIS, RAR ARCHIVES WILL CREATE AN ERROR


2. Navigate to the project directory:

    ```shell
    cd unzipbot
    ```

3. If you prefer using Pipenv:

    - Install Pipenv (if not already installed):

        ```shell
        pip3 install pipenv
        ```

    - Create a virtual environment and install dependencies:

        ```shell
        pipenv install 
        ```
        ...or, so specify the python version overtly:

        ```shell
        pipenv install --python 3.10
        ```


    - Activate the virtual environment:

        ```shell
        pipenv shell
        ```

4. If you prefer using venv and requirements.txt:

    - Create a virtual environment:

        ```shell
        python3 -m venv venv
        ```

    - Activate the virtual environment:

        - On Windows:

            ```shell
            .\venv\Scripts\activate
            ```

        - On macOS and Linux:

            ```shell
            source venv/bin/activate
            ```

    - Install dependencies:

        ```shell
        pip install -r requirements.txt
        ```

5. Make a copy of the template file `sample-config.py` and rename it to `config.py`:

    ```shell
    cp sample-config.py config.py
    ```

6. Open `config.py` and configure the bot token and any other necessary settings.


7. Run the script from your virtual environment shell:

    ```shell
    python unzipbot.py
    ```

## Getting a Bot Token

To run your Telegram bot, you'll need a Bot Token from the Telegram BotFather. Follow these steps to obtain one:

1. Open the Telegram app and search for the "BotFather" bot.

2. Start a chat with BotFather and use the `/newbot` command to create a new bot.

3. Follow the instructions to choose a name and username for your bot.

4. Once your bot is created, BotFather will provide you with a Bot Token. Copy this token.

5. In the `config.py` file, set the `BOT_TOKEN` variable to your Bot Token.




## Usage

COMMANDS

/start - List the archive types you can submit

Once you upload or forward a qualified archive, the bot will announce that is had receved it and will download it to the server in a temp directory. Then it will extract the files. Image and video files are posted as image and video replies. Every other kind of file is posted as a document reply.


## Configuration and Features

The config.py file houses the bot token (as a string between quotes), and the list of terms for which a user will be banned if the term appears in his display name. The finished config file should look something like this:

""" BASIC CREDENTIALS """

\# BASIC CREDENTIALS - BOT TOKEN

\# Gotten from Telegram BotFather

BOT_TOKEN = "XXXXXXXXXXXXXX"  # from BotFather

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.


## Acknowledgments

This bot was built using the python-telegram-bot library and API wrapper. It also uses tqdm for its progress bars.

One python-telegram-bot example bots - chatmemberbot.py - was the model for the function that detence entering/exiting a group:
https://github.com/python-telegram-bot/python-telegram-bot/blob/master/examples/chatmemberbot.py 


## Support
This script is provided AS-IS without warranties of any kind. I am exceptionally lazy, and fixes/improvements will proceed in direct proportion to how much I like you.

"Son...you're on your own." --Blazing Saddles



