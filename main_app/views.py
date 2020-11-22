from django.shortcuts import render, redirect
from .models import State, Question, Result, Profile
from datetime import datetime, timezone, timedelta
from django.db.models import Sum
from django.contrib.auth.models import User
from django.views.generic.edit import CreateView, UpdateView, DeleteView
from django.http import JsonResponse

# Import boto3 library and uuid for generating random strings
import uuid
import boto3
# Django signup
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin

# TO DEFINE LENGTH OF TIME FOR QUESTION AND INTERMISSION PERIOD
question_time = 15000
intermission_time = 10000

# imports for the api
import requests
import json
from html.parser import HTMLParser
from html import unescape
import html
import random

S3_BASE_URL = 'https://s3.us-east-2.amazonaws.com/'
BUCKET = 'projectwolverine'

# When we trigger a refresh for a user, they are sent to this view. This view redirects them based on current game state.
@login_required
def switchboard(request):

  # Set state variable representing current state of game
  state = State.objects.first()
  # Set time_elapsed variable representing time elapsed since last change of state
  time_elapsed = (datetime.now(timezone.utc) - state.time_stamp) / timedelta(microseconds=1) / 1000

  if state.current_state == 'question':
    # If time_elapsed exceeds question_time, it's time to switch to intermission state
    if time_elapsed > question_time:
      # Change state to intermission and set time_stamp
      state.current_state = 'intermission'
      state.time_stamp = datetime.now(timezone.utc)
      state.save()
      # Call get_question function to populate State with new question
      get_question()
      # Redirect user to intermission flow
      return redirect('intermission')
    # If time_elapsed is less than question_time, we're in the question state
    if time_elapsed < question_time:
      # Redirect user to question flow
      return redirect('question')

  if state.current_state == 'intermission':
    # If time_elapsed exceeds intermission_time, it's time to switch to question state
    if time_elapsed > intermission_time:
      # Change state to question and set new time_stamp
      state.current_state = 'question'
      state.time_stamp = datetime.now(timezone.utc)
      state.save()
      # Redirect user to question flow
      return redirect('question')
    # If time_elapsed is less than question_time, we're in the intermission state
    if time_elapsed < intermission_time:
      # Redirect user to intermission flow
      return redirect('intermission')

# User will be sent to this view from the switchboard if the game state is question
@login_required
def question(request):
  # Set variables representing current state, time_left until next state change and question object
  state = State.objects.first()
  time_left = ((state.time_stamp + timedelta(microseconds=(question_time * 1000))) - datetime.now(timezone.utc)) / timedelta(microseconds=1) / 1000
  question = state.question
  # Get leaderboards object
  leaderboards = get_leaderboards()
  # Render question.html
  json_remove_order = json.dumps(question.remove_order)
  return render(request, 'game/question.html', {'question_time':question_time,'time_left': time_left, 'question': question, 'leaderboards':leaderboards, 'remove_order':json_remove_order})

@login_required
def intermission(request):
  state = State.objects.first()
  category = state.question.category
  time_left = ((state.time_stamp + timedelta(microseconds=(intermission_time * 1000))) - datetime.now(timezone.utc)) / timedelta(microseconds=1) / 1000
  # Get leaderboards object
  leaderboards = get_leaderboards()
  message = generate_message(request.user)
  return render(request, 'game/intermission.html', {'message':message,'time_left': time_left, 'category': category, 'leaderboards':leaderboards})

def record_score(request, answer, score):
  # Set variable representing current state
  state = State.objects.first()
  # If the chosen answer is incorrect, make points earned 0
  if answer.strip() != state.question.correct_choice:
    score = 0
  # Create new instance of Result model
  new_result = Result(
    user = request.user,
    points = score,
    answer = answer,
    question = state.question,
    time_stamp = datetime.now(timezone.utc)
  )
  new_result.save()
  answer_class = 'incorrect' if score == 0 else 'correct'
  return redirect(f"/waiting/{new_result.id}")

# When a user selects an answer, they are directed to this flow which determines whether it was correct, 
# adds the result to the db and renders a waiting room until the intermission state
@login_required
def waiting(request, result_id):
  result = Result.objects.get(pk=result_id)
  # Set variable representing current state
  state = State.objects.first()
  # Set variable time_left equal to the remaining time in the question state
  time_left = ((state.time_stamp + timedelta(microseconds=(question_time * 1000))) - datetime.now(timezone.utc)) / timedelta(microseconds=1) / 1000
  # Get leaderboards object
  leaderboards = get_leaderboards()
  # Render waiting.html
  answer_class = 'incorrect' if result.points == 0 else 'correct'
  scoreboard = Result.objects.filter(question=state.question).order_by('-points')
  if state.current_state == 'intermission':
    return redirect('switchboard')
  return render(request, 'game/waiting.html', {'time_left':time_left, 'leaderboards':leaderboards, 'question': state.question, 'answer':result.answer, 'answer_class':answer_class, 'scoreboard':scoreboard, 'result_id':result.id})

def get_question():
  
      # categorys from https://opentdb.com/
  category_list = [
      # sports
      'https://opentdb.com/api.php?amount=1&category=21',
      # general knowledge
      'https://opentdb.com/api.php?amount=1&category=9',
      # movies
      'https://opentdb.com/api.php?amount=1&category=11',
      # music
      'https://opentdb.com/api.php?amount=1&category=12',
      # geography
      'https://opentdb.com/api.php?amount=1&category=22',
      # science: gadgets
      'https://opentdb.com/api.php?amount=1&category=30',
      # science: technology
      'https://opentdb.com/api.php?amount=1&category=18',
      # vehicles
      'https://opentdb.com/api.php?amount=1&category=28',
      # animals
      'https://opentdb.com/api.php?amount=1&category=27',
      # history
      'https://opentdb.com/api.php?amount=1&category=23',
      # video games
      'https://opentdb.com/api.php?amount=1&category=15'
  ]

  category_choice = random.choice(category_list)
  response = requests.get(category_choice)
  data = response.json()

  # Raw data that is retrieved from api     
  incorrect_answers = data['results'][0]['incorrect_answers']
  correct_answer = data['results'][0]['correct_answer']
  category = data['results'][0]['category']
  question = data['results'][0]['question']
  difficulty = data['results'][0]['difficulty']

 # replacing html enities to letters
  wrong_answer_pool = []
  for word in incorrect_answers:
    new_string = word.replace('&quot;', '"').replace('&eacute;',"é").replace('&#039;',"'").replace('&atilde;','ã').replace('&amp;', '&').replace('&aacute;','Á').replace('&ldquo;','"').replace('&rdquo;','"').replace('&gt;',">").replace('&lt;','<').replace('&hellip;','…')
    wrong_answer_pool.append(new_string)

  #Data that is 'unescaped' to deal with unicode issues.  
  question_string = html.unescape(question)
  answer_string = html.unescape(correct_answer)
  category_string = html.unescape(category)
  difficulty_string = html.unescape(difficulty)
  
  # This creates a answer pool in a random order using random method
  wrong_answer_pool += [answer_string]  
  wrong_answer_pool = random.sample(wrong_answer_pool,len(wrong_answer_pool))
  # wrong_answer_pool is now a radomized list with the answer as well

  # Create remove_order
  remove_order = list(wrong_answer_pool)
  remove_order.remove(answer_string)
  random.shuffle(remove_order)
  remove_order.pop()

  # Create new instance of Question model
  new_question = Question(
    question=question_string,
    choices=wrong_answer_pool,
    time_stamp=datetime.now(timezone.utc),
    correct_choice=answer_string,
    category=category_string,
    difficulty=difficulty_string,
    remove_order=remove_order
  )
  new_question.save()

  # Save new instance of Question as the question in State
  state = State.objects.first()
  state.question = new_question
  state.save()

def signup(request):
  error_message = ''
  if request.method == 'POST':
    # This is what creates a user object that has the data from the browser
    form = UserCreationForm(request.POST)
    if form.is_valid():
      # The saves the user to the database if the form is valid
      user = form.save()
      login(request, user)
      return redirect('login')
    else:
      error_message = 'Invalid sign up - try again'
  # Error Handling. We should make a cool 404 page.
  form = UserCreationForm()
  context = {'form': form, 'error_message': error_message}
  return render(request, 'registration/signup.html', context)

def play(request):
  return render(request, 'main_app/play.html')

def info(request):
  return render(request, 'main_app/info.html')

@login_required
def pause(request):
  return render(request,'game/pause.html')

def get_leaderboards():
  
  # Set variable for current time
  now = datetime.now(timezone.utc)

  # Create queries for each leaderboard that sum points by user
  hour = Result.objects.filter(time_stamp__gte= now - timedelta(hours=1)).values('user__username').annotate(Sum('points')).order_by('-points__sum')
  day = Result.objects.filter(time_stamp__gte= now - timedelta(days=1)).values('user__username').annotate(Sum('points')).order_by('-points__sum')
  week = Result.objects.filter(time_stamp__gte= now - timedelta(days=7)).values('user__username').annotate(Sum('points')).order_by('-points__sum')
  month = Result.objects.filter(time_stamp__gte= now - timedelta(days=30)).values('user__username').annotate(Sum('points')).order_by('-points__sum')
  alltime = Result.objects.values('user__username').annotate(Sum('points')).order_by('-points__sum')

  # Create and return leaderboards object
  leaderboards = {
    'hour': hour,
    'day': day,
    'week': week,
    'month': month,
    'alltime': alltime
  }

  return leaderboards

@login_required
def profile_detail(request, user_id,):
  user = User.objects.get(id=user_id)
  profile = Profile.objects.get(user__id=user_id)
  # Get leaderboards object
  leaderboards = get_leaderboards()
  return render(request, 'main_app/detail.html', {
    'user':user,
    'profile':profile,
    'leaderboards':leaderboards,
  })


def add_photo(request, user_id):
    # photo-file will be the "name" attribute on the <input type="file">
    photo_file = request.FILES.get('photo-file', None)
    if photo_file:
        s3 = boto3.client('s3')
        # need a unique "key" for S3 / needs image file extension too
        key = uuid.uuid4().hex[:6] + photo_file.name[photo_file.name.rfind('.'):]
        # just in case something goes wrong
        try:
            s3.upload_fileobj(photo_file, BUCKET, key)
            # build the full url string
            url = f"{S3_BASE_URL}{BUCKET}/{key}"
            # we can assign profile (if you have a profile object)
            profile = Profile.objects.get(user__id=user_id)
            profile.url = url
            profile.save()
        except:
            print('An error occurred uploading file to S3')
    return redirect('detail', user_id=user_id)

class ProfileCreate(LoginRequiredMixin, CreateView):
  model = Profile
  fields = '__all__'
  success_url = '/play'

class ProfileUpdate(LoginRequiredMixin, UpdateView):
  model = Profile
  fields = ['quip']

class ProfileDelete(LoginRequiredMixin, DeleteView):
  model = Profile
  success_url = '/accounts/login'

def refresh_scoreboard(request):
  state = State.objects.first()
  scoreboard_query = Result.objects.filter(question=state.question).order_by('-points')
  scoreboard = []
  for score in scoreboard_query:
    user = score.user.username
    points = score.points
    url = score.user.profile.url
    quip = score.user.profile.quip
    scoreboard_item = {
      'user': score.user.username,
      'points': score.points,
      'url': score.user.profile.url,
      'quip': score.user.profile.quip
    }
    scoreboard.append(scoreboard_item)
  return JsonResponse(scoreboard, safe=False)

def generate_message(user):
  message_type = [
    rank,
    tip,
    fact,
  ]
  return random.choice(message_type)(user)

def rank(user):
  message_list = [
    hourly,
    daily,
    weekly,
    monthly,
    alltime
  ]
  return random.choice(message_list)(user)

def hourly(user):
  now = datetime.now(timezone.utc)
  points = Result.objects.filter(user=user).filter(time_stamp__gte= now - timedelta(hours=1)).aggregate(Sum('points'))
  rank = Result.objects.filter(time_stamp__gte= now - timedelta(hours=1)).values('user__username').annotate(points=Sum('points')).filter(points__gt=points['points__sum']).count() + 1
  if rank == 1:
    return f"You are currently the player of the hour with {points['points__sum']} points!"
  elif rank == 2:
    return f"You are the 2nd ranked player in the past hour with {points['points__sum']} points!"
  elif rank == 3:
    return f"You are the 3rd ranked player in the past hour with {points['points__sum']} points!"
  else:
    return f"You are the {rank}th ranked player in the past hour with {points['points__sum']} points."

def daily(user):
  now = datetime.now(timezone.utc)
  points = Result.objects.filter(user=user).filter(time_stamp__gte= now - timedelta(days=1)).aggregate(Sum('points'))
  rank = Result.objects.filter(time_stamp__gte= now - timedelta(days=1)).values('user__username').annotate(points=Sum('points')).filter(points__gt=points['points__sum']).count() + 1
  if rank == 1:
    return f"You are currently the player of the past day with {points['points__sum']} points!"
  elif rank == 2:
    return f"You are the 2nd ranked player in the past day with {points['points__sum']} points!"
  elif rank == 3:
    return f"You are the 3rd ranked player in the past day with {points['points__sum']} points!"
  else:
    return f"You are the {rank}th ranked player in the past day with {points['points__sum']} points."

def weekly(user):
  now = datetime.now(timezone.utc)
  points = Result.objects.filter(user=user).filter(time_stamp__gte= now - timedelta(weeks=1)).aggregate(Sum('points'))
  rank = Result.objects.filter(time_stamp__gte= now - timedelta(weeks=1)).values('user__username').annotate(points=Sum('points')).filter(points__gt=points['points__sum']).count() + 1
  if rank == 1:
    return f"You are currently the player of the past week with {points['points__sum']} points!"
  elif rank == 2:
    return f"You are the 2nd ranked player in the past week with {points['points__sum']} points!"
  elif rank == 3:
    return f"You are the 3rd ranked player in the past week with {points['points__sum']} points!"
  else:
    return f"You are the {rank}th ranked player in the past week with {points['points__sum']} points."

def monthly(user):
  now = datetime.now(timezone.utc)
  points = Result.objects.filter(user=user).filter(time_stamp__gte= now - timedelta(days=30)).aggregate(Sum('points'))
  rank = Result.objects.filter(time_stamp__gte= now - timedelta(days=30)).values('user__username').annotate(points=Sum('points')).filter(points__gt=points['points__sum']).count() + 1
  if rank == 1:
    return f"You are currently the player of the past month with {points['points__sum']} points!"
  elif rank == 2:
    return f"You are the 2nd ranked player in the past month with {points['points__sum']} points!"
  elif rank == 3:
    return f"You are the 3rd ranked player in the past month with {points['points__sum']} points!"
  else:
    return f"You are the {rank}th ranked player in the past month with {points['points__sum']} points."

def alltime(user):
  now = datetime.now(timezone.utc)
  points = Result.objects.filter(user=user).aggregate(Sum('points'))
  rank = Result.objects.values('user__username').annotate(points=Sum('points')).filter(points__gt=points['points__sum']).count() + 1
  if rank == 1:
    return f"You are currently the greatest of all time with {points['points__sum']} points!"
  elif rank == 2:
    return f"You are the 2nd ranked player of all time with {points['points__sum']} points!"
  elif rank == 3:
    return f"You are the 3rd ranked player of all time with {points['points__sum']} points!"
  else:
    return f"You are the {rank}th ranked player of all time with {points['points__sum']} points."

def tip(user):
  message_list = [
    leaderboard,
    remove_incorrect,
    more_points,
    change_avatar,
    change_quip,
    invite
  ]
  return random.choice(message_list)()

def leaderboard():
  return "Tap the trophy in the top right to see the leaderboards."

def remove_incorrect():
  return "Take your time. We remove incorrect answers as time goes on."

def more_points():
  return "You get more points the faster you answer the question."

def change_avatar():
  return "You can change your avatar by tapping the avatar in the top left."

def change_quip():
  return "The first person to answer gets to broadcast their quip to the rest of the players. Change yours by clicking the avatar in the top left."

def invite():
  return "Invite your friends to play! The more the merrier!"

def fact(user):
  message_list = [
    creators,
    technology,
    seb,
    nick,
    jermaine,
    duration,
    framework,
    headbanging,
    guinea,
    tickle,
    snakes,
    crows,
    yourmom,
    diseases,
    pillow,
    fearfun,
    kangaroo
  ]
  return random.choice(message_list)()

def creators():
  return "This game was built by Jermaine, Nick and Seb. They're great!"

def technology():
  return "This game was built with Django, Python, JavaScript, HTML, CSS and lots more!"

def seb():
  return "Check Sebastien Beitel out on LinkedIn!"

def nick():
  return "Check Nick Mackenzie out on LinkedIn!"

def jermaine():
  return "Check Jermaine Blake out on LinkedIn!"

def duration():
  return "This game was built in less than a week"

def framework():
  return "The frontend framework was made from scratch. No Bootstrap or Bulma needed"

def headbanging():
  return "Banging your head against a wall for one hour burns 150 calories."

def guinea():
  return "In Switzerland it is illegal to own just one guinea pig."

def tickle():
  return "Pteronophobia is the fear of being tickled by feathers."

def snakes():
  return "Snakes can help predict earthquakes."

def crows():
  return "Crows can hold grudges against specific individual people."

def yourmom():
  return "The oldest “your mom” joke was discovered on a 3,500 year old Babylonian tablet."

def diseases():
  return "So far, two diseases have successfully been eradicated: smallpox and rinderpest."

def pillow():
  return "29th May is officially “Put a Pillow on Your Fridge Day”."

def fearfun():
  return "Cherophobia is an irrational fear of fun or happiness."
def kangaroo():
  return "If you lift a kangaroo’s tail off the ground it can’t hop."