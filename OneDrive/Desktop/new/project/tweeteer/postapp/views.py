from django.shortcuts import render
from .models import Post
from .forms import postForm,UserRegistrationForm
from django.shortcuts import get_object_or_404,redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.views.generic import ListView
from django.db.models import Q

def index(request):
    return render(request,'index.html')

def post_list(request):
    posts = Post.objects.all().order_by('-created_at')
    return render(request,'post_list.html',{'posts':posts})   #used in post_list.html

@login_required
def post_create(request):
    if request.method == "POST":
        form = postForm(request.POST,request.FILES)
        if form.is_valid():
            post = form.save(commit=False)
            post.user = request.user
            post.save()
            return redirect('post_list')
    else:
        form = postForm()
    
    return render(request,'post_form.html', {'form':form})

@login_required
def post_edit(request,post_id):
    post = get_object_or_404(Post,pk=post_id,user = request.user)
    if request.method == "POST":
        form = postForm(request.POST,request.FILES,instance=post)
        if form.is_valid():
            post = form.save(commit=False)
            post.user = request.user
            post.save()                #save the updated post 
            return redirect('post_list') 

    else:
        form = postForm(instance=post)
    return render(request,'post_form.html', {'form':form})

@login_required
def post_delete(request,post_id):
    post_to_be_deleted = get_object_or_404(Post,pk=post_id,user=request.user)
    if request.method == 'POST':
        post_to_be_deleted.delete()
        return redirect('post_list')
    return render(request,'post_confirm_delete.html',{'post_delete':post_delete})

def Register(request):
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password1'])
            form.save()
            login(request,user)
            return redirect('post_list')
        else:
            print(form.errors)
    else:
        form = UserRegistrationForm()

    return render(request,'registration/register.html',{'form':form})


class ModelListView(ListView):
    model = Post
    template_name = "searchResult.html"
    def get_queryset(self):
        query = self.request.GET.get('searchPost')
        print("search query:"+query)
        if query:
            return Post.objects.filter(
                 Q(text__icontains=query) | Q(user__username__icontains=query)
            )
        return Post.objects.all()
