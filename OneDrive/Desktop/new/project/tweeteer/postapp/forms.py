from django import forms
from .models import Post
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import  User

class postForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = ['text','photo']

class UserRegistrationForm(UserCreationForm):
    email = forms.EmailField()
    class Meta:
        model = User
        fields = ('username','email','password1','password2')                                 #here we use tuple instead of array like above beacause we are using the default django forms
        