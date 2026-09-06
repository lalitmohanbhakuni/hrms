from django import forms
from django.contrib.auth.models import User
from .models import EmployeeProfile

class EmployeeForm(forms.ModelForm):
    # User fields
    username = forms.CharField(max_length=150, required=True, widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={'class': 'form-control'}))
    password1 = forms.CharField(label='Password', widget=forms.PasswordInput(attrs={'class': 'form-control'}), required=False)
    password2 = forms.CharField(label='Confirm Password', widget=forms.PasswordInput(attrs={'class': 'form-control'}), required=False)
    
    # Profile fields
    employee_id = forms.CharField(max_length=20, required=True, widget=forms.TextInput(attrs={'class': 'form-control'}))
    full_name = forms.CharField(max_length=100, required=True, widget=forms.TextInput(attrs={'class': 'form-control'}))
    date_of_birth = forms.DateField(required=False, widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}))
    date_of_joining = forms.DateField(required=False, widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}))
    designation = forms.CharField(max_length=100, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    department = forms.CharField(max_length=100, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    phone = forms.CharField(max_length=20, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    address = forms.CharField(required=False, widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}))
    
    class Meta:
        model = EmployeeProfile
        fields = ['employee_id', 'full_name', 'date_of_birth', 'date_of_joining', 
                  'designation', 'department', 'phone', 'address']
    
    def clean_username(self):
        username = self.cleaned_data.get('username')
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError('Username already exists.')
        return username
    
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('Email already registered.')
        return email
    
    def clean_employee_id(self):
        emp_id = self.cleaned_data.get('employee_id')
        if EmployeeProfile.objects.filter(employee_id=emp_id).exists():
            raise forms.ValidationError('Employee ID already exists.')
        return emp_id
    
    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')
        if password1 and password2 and password1 != password2:
            self.add_error('password2', 'Passwords do not match.')
        return cleaned_data
    
    def save(self, commit=True):
        # Create User
        user = User.objects.create_user(
            username=self.cleaned_data['username'],
            email=self.cleaned_data['email'],
            password=self.cleaned_data['password1']
        )
        # Create Profile
        profile = EmployeeProfile.objects.create(
            user=user,
            employee_id=self.cleaned_data['employee_id'],
            full_name=self.cleaned_data['full_name'],
            date_of_birth=self.cleaned_data.get('date_of_birth'),
            date_of_joining=self.cleaned_data.get('date_of_joining'),
            designation=self.cleaned_data.get('designation', ''),
            department=self.cleaned_data.get('department', ''),
            phone=self.cleaned_data.get('phone', ''),
            address=self.cleaned_data.get('address', '')
        )
        return profile