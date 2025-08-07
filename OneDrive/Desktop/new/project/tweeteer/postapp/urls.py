from django.urls import path
from .import views
from .views import ModelListView

urlpatterns = [
    path('',views.post_list,name='post_list'),
    path('create/',views.post_create,name='post_create'),
    path('<int:post_id>/delete/',views.post_delete,name='post_delete'),       #while editing post id is needed
    path('<int:post_id>/edit/',views.post_edit,name='post_edit'),
    path('register/',views.Register,name='Register'),
    path('search/', ModelListView.as_view(), name='post_search'),
    
]
