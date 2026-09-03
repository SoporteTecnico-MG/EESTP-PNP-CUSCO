from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "asistencia"

urlpatterns = [
    path("", views.home, name="home"),
    path("nosotros/", views.nosotros, name="nosotros"),
    path("convocatorias/", views.convocatorias, name="convocatorias"),
    path("contacto/", views.contacto, name="contacto"),
    path("login/", auth_views.LoginView.as_view(template_name="asistencia/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("despues-login/", views.post_login_redirect, name="post_login_redirect"),
    path("aula-virtual/", views.aula_virtual, name="aula_virtual"),
    path("mi-cuenta/", views.mi_cuenta, name="mi_cuenta"),
]
