from django import forms
from django.contrib.auth.models import User
from .models import EmployeeProfile
from .models import OfficeLocation  # import at top

class EmployeeForm(forms.ModelForm):
    # User fields
    username = forms.CharField(max_length=150, required=True, widget=forms.TextInput(attrs={'class': 'form-control'}))
    # email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(required=False, widget=forms.EmailInput(attrs={'class': 'form-control'}))
    password1 = forms.CharField(label='Password', widget=forms.PasswordInput(attrs={'class': 'form-control'}), required=False)
    password2 = forms.CharField(label='Confirm Password', widget=forms.PasswordInput(attrs={'class': 'form-control'}), required=False)
    
    # Profile fields (employee_id REMOVED from here)
    full_name = forms.CharField(max_length=100, required=True, widget=forms.TextInput(attrs={'class': 'form-control'}))
    date_of_birth = forms.DateField(required=False, widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}))
    date_of_joining = forms.DateField(required=False, widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}))
    designation = forms.CharField(max_length=100, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    department = forms.CharField(max_length=100, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    phone = forms.CharField(max_length=20, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    address = forms.CharField(required=False, widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}))
    
    
    attendance_type = forms.ChoiceField(
        choices=EmployeeProfile.ATTENDANCE_TYPES,
        required=True,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    office_location = forms.ModelChoiceField(
        queryset=OfficeLocation.objects.filter(is_active=True),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    manager = forms.ModelChoiceField(
        queryset=EmployeeProfile.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    # In EmployeeForm class
    role = forms.ChoiceField(
        choices=EmployeeProfile.ROLE_CHOICES,
        required=True,
        initial='employee',
        widget=forms.Select(attrs={'class': 'form-control'})
    )


    class Meta:
        model = EmployeeProfile
        fields = ['full_name', 'date_of_birth', 'date_of_joining', 
                  'designation', 'department', 'phone', 'address',
                  'attendance_type', 'office_location', 'manager', 'role']  # added fields

    
    
    def clean_username(self):
        username = self.cleaned_data.get('username')
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError('Username already exists.')
        return username
    
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email:  # Only check uniqueness if email is provided
            if User.objects.filter(email=email).exists():
                raise forms.ValidationError('Email already registered.')
        return email
    
    # clean_employee_id REMOVED (no longer needed)
    
    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')
        if password1 and password2 and password1 != password2:
            self.add_error('password2', 'Passwords do not match.')
        return cleaned_data
    
    def save(self, employee_id=None, company=None, commit=True):
        # Create User
        user = User.objects.create_user(
            username=self.cleaned_data['username'],
            email=self.cleaned_data['email'],
            password=self.cleaned_data['password1']
        )
        # Create Profile – now with employee_id and company
        profile = EmployeeProfile.objects.create(
            user=user,
            employee_id=employee_id,  # <-- Passed from the view
            company=company,           # <-- Passed from the view
            full_name=self.cleaned_data['full_name'],
            date_of_birth=self.cleaned_data.get('date_of_birth'),
            date_of_joining=self.cleaned_data.get('date_of_joining'),
            designation=self.cleaned_data.get('designation', ''),
            department=self.cleaned_data.get('department', ''),
            phone=self.cleaned_data.get('phone', ''),
            address=self.cleaned_data.get('address', '')
        )
        return profile