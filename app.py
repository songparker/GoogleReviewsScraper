import csv
import os
import re
import time
from datetime import datetime, timedelta

import bcrypt
import googlemaps
from bs4 import BeautifulSoup
from flask import Flask, request, render_template, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.keys import Keys
from sqlalchemy.exc import NoResultFound

from forms import LoginForm, RegisterForm, AccountForm
from models import db, DBUser, Reviews, create_all
import random

app = Flask(__name__)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
app.config['SQLALCHEMY_DATABASE_URI'] = r'sqlite:///users.sqlite'
app.config['DEBUG'] = True
db.init_app(app)
# Replace 'Your_API_Key' with your real google API key for testing
gmaps = googlemaps.Client(key='Your_API_Key')
app.secret_key = os.environ.get('SECRET_KEY', 'fallback_secret_key_if_env_var_not_set')

if not os.path.isfile("users.sqlite"):
    create_all(app)


class User(UserMixin):
    def __init__(self, username, email, phone, password=None):
        self.id = username
        self.email = email
        self.phone = phone
        self.password = password


# this is used by flask_login to get a user object for the current user
@login_manager.user_loader
def load_user(user_id):
    user = find_user(user_id)
    if user:
        db_user = DBUser.query.filter_by(username=user_id).first()
        user.password = db_user.password
    return user


def find_user(username):
    res = DBUser.query.filter_by(username=username).first()
    if res:
        user = User(res.username, res.email, res.phone, res.password)
    else:
        user = None
    return user


def relative_to_absolute_date(relative_date_str):
    # Current date
    now = datetime.now()

    # Look for number and unit
    match = re.search(r'(\d+)\s*(second|minute|hour|day|week|month|year)[s]* ago', relative_date_str)

    if match is None:
        # handle "a month ago" or "an hour ago"
        match = re.search(r'(a|an)\s*(second|minute|hour|day|week|month|year)[s]* ago', relative_date_str)

        if match is None:
            return None
        else:
            number = 1  # "a" or "an" represents one unit
            unit = match.group(2)
    else:
        number = int(match.group(1))
        unit = match.group(2)

    # Subtract the appropriate amount of time
    if unit == "second":
        return (now - timedelta(seconds=number)).date()
    elif unit == "minute":
        return (now - timedelta(minutes=number)).date()
    elif unit == "hour":
        return (now - timedelta(hours=number)).date()
    elif unit == "day":
        return (now - timedelta(days=number)).date()
    elif unit == "week":
        return (now - timedelta(weeks=number)).date()
    elif unit == "month":
        return (now - timedelta(days=30 * number)).date()  # Approximate
    elif unit == "year":
        return (now - timedelta(days=365 * number)).date()  # Approximate
    return None


def get_place_id(place_name):
    try:
        place_result = gmaps.places(place_name)
        if place_result and 'results' in place_result and place_result['results']:
            place_id = place_result['results'][0]['place_id']
            official_place_name = place_result['results'][0]['name']  # Get the official name
            print("Place Name: ", official_place_name)
            print("Place ID: ", place_id)
            return place_id, official_place_name
        else:
            print(f"No place found for: {place_name}")
            return None, place_name
    except Exception as e:
        print(f"Error occurred while fetching place_id for: {place_name}")
        print(f"Exception: {e}")
        return None, place_name


def scrape_all_reviews(driver, number_reviews):
    reviews = []

    review_selector = "//div[contains(@class, 'jftiEf fontBodyMedium ')]"
    scraped_count = 0
    last_processed = None

    # Counters to stop the loop in case of no progress
    no_progress_count = 0
    max_no_progress_attempts = 20  # Or any other number you find suitable

    while scraped_count < number_reviews:
        current_reviews = driver.find_elements(By.XPATH, review_selector)
        if not current_reviews:
            print("No reviews found. Waiting for the reviews to load...")
            time.sleep(random.uniform(0.1, 0.5))
            continue

        # Scroll to the last review
        driver.execute_script("arguments[0].scrollIntoView();", current_reviews[-1])

        time.sleep(random.uniform(0.1, 0.5))

        # Check if there are owner's responses and scroll to the end of them
        try:
            owner_response_elem = current_reviews[-1].find_element(By.XPATH, ".//span[text()='Response from the owner']"
                                                                            "/following::div[@class='wiI7pd'][1]")
            scroll_height_before = driver.execute_script('return document.documentElement.scrollHeight;')
            driver.execute_script("arguments[0].scrollIntoView();", owner_response_elem)

            time.sleep(random.uniform(0.1, 0.5))

            scroll_height_after = driver.execute_script('return document.documentElement.scrollHeight;')

            if scroll_height_before == scroll_height_after:
                # If the page did not scroll down after trying to scroll to the owner's response, scroll down a bit more
                actions = ActionChains(driver)
                actions.send_keys(Keys.PAGE_DOWN)
                actions.perform()

                time.sleep(random.uniform(0.1, 0.5))
        except NoSuchElementException:
            # No owner response, continue to the next review
            pass

        new_reviews = driver.find_elements(By.XPATH, review_selector)
        new_scraped_count = len(new_reviews)

        # Check if there is any progress
        if new_scraped_count > scraped_count:
            # If progress, reset the no progress counter and print the progress
            no_progress_count = 0
            scraped_count = new_scraped_count
            print(f"{scraped_count}/{number_reviews} reviews scraped, in progress...")
        else:
            # If no progress, increment the no progress counter
            no_progress_count += 1

        # If no progress for max_no_progress_attempts attempts, break the loop and save the already scraped reviews
        if no_progress_count >= max_no_progress_attempts:
            print(f"Scraping stopped due to no progress. {scraped_count} reviews scraped.")
            break

    print(f"{scraped_count}/{number_reviews} reviews scraped, done.\n")

    # Parse each review
    for index, review in enumerate(new_reviews, start=1):
        try:
            reviewer = review.find_element(By.XPATH, ".//div[contains(@class, 'd4r55 ')]").text
            rating_html = review.find_element(By.XPATH, ".//span[contains(@class, 'kvMYJc')]").get_attribute(
                'innerHTML')
            rating_soup = BeautifulSoup(rating_html, 'html.parser')
            rating = len(
                rating_soup.find_all('img', {'src': '//maps.gstatic.com/consumer/images/icons/2x/ic_star_rate_14.png'}))
            # Get review time
            review_time_relative = review.find_element(By.XPATH, ".//span[contains(@class, 'rsqaWe')]").text
            review_time_absolute = relative_to_absolute_date(review_time_relative)  # Approximate

            # Get review content
            try:
                review_content = review.find_element(By.XPATH, ".//span[contains(@class, 'wiI7pd')]").text
                try:
                    read_more_button = review.find_element(By.XPATH, ".//button[text()='More']")
                    if read_more_button:
                        # Click "More" to reveal full text
                        read_more_button.click()
                        review_content = review.find_element(By.XPATH, ".//span[contains(@class, 'wiI7pd')]").text
                except NoSuchElementException:
                    pass  # If no 'More' button is present
            except NoSuchElementException:
                review_content = "No review text provided."

            # Check for owner's response after review content
            try:
                owner_response = review.find_element(By.XPATH,
                                                     ".//span[text()='Response from the owner']"
                                                     "/following::div[@class='wiI7pd'][1]").text
            except NoSuchElementException:
                owner_response = None

            reviews.append({
                'id': index,
                'reviewer': reviewer,
                'rating': rating,
                'review_time': review_time_absolute,
                'review_content': review_content,
                'owner_response': owner_response
            })

            # No need to print the json since we already have showing them on front end.
            # And we have csv version. Printing them waste time and console space
            # print(f"ID: {index}")
            # print(f"Reviewer: {reviewer}")
            # print(f"Rating: {rating}")
            # print(f"Review Time: {review_time_absolute}")
            # print(f"review_content: {review_content}")
            # print(f"owner_response: {owner_response}")
            # print("\n")  # line break

        except Exception as e:
            print("Problem occurred while processing a review.")
            print(f"Exception: {e}")
            continue

    return reviews


def get_all_reviews(place_url, number_reviews):
    # Setup firefox options
    firefox_options = webdriver.FirefoxOptions()
    # firefox_options.add_argument("--headless")

    # Set the browser's zoom level to 50%
    firefox_options.set_preference("layout.css.devPixelsPerPx", "0.5")

    # Set path to geckodriver as per your configuration, change it to your path accordingly
    webdriver_service = Service(r'D:\My Files\download\geckodriver.exe')

    driver = webdriver.Firefox(service=webdriver_service, options=firefox_options)

    driver.get(place_url)

    # Add a delay for the page to load
    time.sleep(5)

    # Find the Reviews button and click it
    try:
        reviews_button = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH, '//button[starts-with(@aria-label, "Reviews for") and @role="tab"]')))
    except TimeoutException:
        print("No reviews to scrape. The location does not have any reviews.")
        driver.quit()
        return [], None, None

    actions = ActionChains(driver)
    actions.move_to_element(reviews_button).perform()
    reviews_button.click()
    time.sleep(3)

    # Get overall rating after clicking the Reviews button
    try:
        rating_overall_element = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.XPATH, '//div[@class="fontDisplayLarge"]')))
        rating_overall = float(rating_overall_element.text)
        total_reviews_element = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.XPATH, '//div[@class="fontBodySmall" and contains(text(), "reviews")]')))
        total_reviews_text = total_reviews_element.text.split()[0]
        total_reviews = int(total_reviews_text.replace(',', ''))
        print(f"Overall rating: {rating_overall}\n")
        print(f"Total reviews: {total_reviews}\n")
    except TimeoutException:
        print("Could not find the overall rating or total reviews number.")
        driver.quit()
        return [], None, None

    # Add a delay for the reviews to load
    time.sleep(2)

    if number_reviews > total_reviews:
        print("The specified number of reviews is greater than the total available reviews.")
        number_reviews = total_reviews

    reviews = scrape_all_reviews(driver, number_reviews)

    driver.quit()

    # If no reviews found...
    if len(reviews) == 0:
        return [], None, None

    return reviews, rating_overall, number_reviews


def format_filename(official_place_name, overall_rating, total_reviews):
    # Properly case the place name and remove spaces
    formatted_place = ''.join(official_place_name.split())
    # Combine the filename
    filename = f"{formatted_place}_{overall_rating}_{total_reviews}_Reviews.csv"
    return filename


@app.route('/', methods=['GET', 'POST'])
@login_required
def home():
    reviews = []
    place_name = ''
    place_id = ''
    place_url = ''
    error_message = ''
    overall_rating = ''
    total_reviews = ''

    if request.method == 'POST':
        place_name = request.form.get('place_name')
        total_reviews = request.form.get('number_reviews')

        if not place_name or not total_reviews:
            flash("Please enter a place name and the number of reviews you want to scrape.")
        else:
            try:
                total_reviews = int(total_reviews)
                if total_reviews <= 0:
                    flash("No. of reviews must be greater than zero.", category="error")
                    return redirect(url_for('home'))
            except ValueError:
                flash("Invalid input for the number of reviews. Please enter a valid number.", category="error")
                return redirect(url_for('home'))

            place_id, place_name = get_place_id(place_name)
            if place_id:
                place_url = f'https://www.google.com/maps/place/?q=place_id:{place_id}'
                print("Place URL: ", place_url)
                reviews, overall_rating, _ = get_all_reviews(place_url, total_reviews)
                flash("Scraping finished!", category="success")

                if not reviews and overall_rating is None:
                    total_reviews = 0
                    flash(f"No reviews found for: {place_name}")
                else:
                    total_available_reviews = len(reviews)
                    if total_reviews > total_available_reviews:
                        flash(f"The specified number of reviews ({total_reviews}) is greater than the total number of available reviews ({total_available_reviews}).")
                        total_reviews = total_available_reviews
                    reviews = reviews[:total_reviews]

            else:
                total_reviews = 0
                flash(f"No place found for: {place_name}")

    # Save to Database
    if len(reviews) > 0:
        try:
            for review_data in reviews:
                # Check if a review with the same review_id and place_name already exists in the database
                existing_review = Reviews.query.filter_by(review_id=review_data['id'], place_name=place_name).first()

                if existing_review:
                    # Skip saving the review if a duplicate already exists
                    continue

                # Save the review to the database
                review = Reviews(
                    review_id=review_data['id'],
                    user_id=current_user.id,
                    place_name=place_name,
                    reviewer=review_data['reviewer'],
                    rating=review_data['rating'],
                    review_time=review_data['review_time'],
                    review_content=review_data['review_content'],
                    owner_response=review_data['owner_response']
                )
                db.session.add(review)
                db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Error while saving review in the database: {e}")

        # Write to CSV
        try:
            # Specify the folder path
            folder = 'output_data'

            # Create the folder if it doesn't exist
            os.makedirs(folder, exist_ok=True)

            filename = format_filename(place_name, overall_rating, total_reviews)
            filepath = os.path.join(folder, filename)

            with open(filepath, 'w', newline='', encoding='utf-8') as file:
                writer = csv.writer(file)
                writer.writerow(["ID", "Reviewer", "Rating", "Review Time", "Review Content", "Owner Response"])

                for review in reviews:
                    writer.writerow([
                        review['id'],
                        review['reviewer'],
                        review['rating'],
                        review['review_time'],
                        review['review_content'],
                        review['owner_response'] if review['owner_response'] is not None else "None"
                    ])

            print(f"Reviews exported to {filepath}")
        except Exception as e:
            print(f"Error while writing to file: {e}")

    return render_template('home.html', place_name=place_name, place_id=place_id, place_url=place_url,
                           error_message=error_message, overall_rating=overall_rating, total_reviews=total_reviews,
                           reviews=reviews)


@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = find_user(form.username.data)
        # user could be None
        # passwords are kept in hashed form, using the bcrypt algorithm
        if user and bcrypt.checkpw(form.password.data.encode(), user.password.encode()):
            login_user(user)
            flash('Logged in successfully.')

            return redirect(url_for('home'))
        else:
            flash('Incorrect username/password!')
    return render_template('login.html', form=form)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    # flash(str(session))
    return redirect('/login')


@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        # check first if user already exists
        user = find_user(form.username.data)
        if not user:
            salt = bcrypt.gensalt()
            password = bcrypt.hashpw(form.password.data.encode(), salt)
            user = DBUser(username=form.username.data, email=form.email.data, phone=form.phone.data,
                          password=password.decode())
            db.session.add(user)
            db.session.commit()
            flash('Registered successfully.')
            return redirect('/login')
        else:
            flash('This username already exists, choose another one')
    return render_template('register.html', form=form)


@app.route('/account', methods=['GET', 'POST'])
@login_required
def account():
    form = AccountForm(obj=current_user)
    form.username.data = current_user.id  # Set the current username in the form

    if form.validate_on_submit():
        if bcrypt.checkpw(form.oldPassword.data.encode(), current_user.password.encode()):
            try:
                user = DBUser.query.filter_by(username=current_user.id).one()
                user.email = form.email.data
                user.phone = form.phone.data
                if form.newPassword.data:
                    password_hash = bcrypt.hashpw(form.newPassword.data.encode(), bcrypt.gensalt())
                    user.password = password_hash.decode()
                db.session.commit()  # Save the changes to the database
                flash('Your account has been updated!')
                return redirect(url_for('home'))
            except NoResultFound:
                flash('User not found in the database.')
        else:
            flash('Incorrect old password. Please try again.')

    return render_template('account.html', form=form)


@app.route('/all_reviews', methods=['GET'])
@login_required
def all_reviews():
    reviews = Reviews.query.filter_by(user_id=current_user.id).all()

    return render_template('all_reviews.html', reviews=reviews)


@app.route('/delete_reviews', methods=['POST'])
@login_required
def delete_reviews():
    if 'review_ids' in request.form:
        review_ids = request.form.getlist('review_ids')
        if not review_ids:
            flash("No reviews selected for deletion.", category="error")
        else:
            try:
                deleted_reviews = Reviews.query.filter(Reviews.user_id == current_user.id,
                                                       Reviews.id.in_(review_ids)).delete(synchronize_session=False)
                db.session.commit()
                flash(f"Successfully deleted {deleted_reviews} review(s).", category="success")
                print(f"Successfully deleted {deleted_reviews} review(s).")
            except Exception as e:
                db.session.rollback()
                flash("An error occurred while deleting the reviews.", category="error")
                print(f"Error while deleting reviews: {e}")
    else:
        flash("No reviews selected for deletion.", category="error")

    return redirect(url_for('all_reviews'))


@app.route('/sort_reviews', methods=['GET'])
@login_required
def sort_reviews():
    option = request.args.get('option')
    order = request.args.get('order')

    sort_options = {
        'id': Reviews.id,
        'place_name': Reviews.place_name,
        'reviewer': Reviews.reviewer,
        'rating': Reviews.rating,
        'review_time': Reviews.review_time,
        'review_content': Reviews.review_content,
        'owner_response': Reviews.owner_response
    }

    if option in sort_options:
        column = sort_options[option]
        if order == 'desc':
            column = column.desc()

        reviews = Reviews.query.filter_by(user_id=current_user.id).order_by(column).all()
    else:
        reviews = Reviews.query.filter_by(user_id=current_user.id).all()

    return render_template('all_reviews.html', reviews=reviews)


if __name__ == '__main__':
    app.run(debug=True)
