from django import forms
from django.contrib.auth.models import User
from .models import EmployeeProfile
from .models import OfficeLocation  # import at top
from django.contrib.auth.password_validation import validate_password




class EmployeeForm(forms.ModelForm):
    # User fields
    username = forms.CharField(max_length=150, required=True, widget=forms.TextInput(attrs={'class': 'form-control'}))
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
        queryset=OfficeLocation.objects.none(),          # populated in __init__
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    manager = forms.ModelChoiceField(
        queryset=EmployeeProfile.objects.none(),          # populated in __init__
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
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
                  'attendance_type', 'office_location', 'manager', 'role']

    # ── NEW: company-scoped dropdowns ──
    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        if company is not None:
            self.fields['office_location'].queryset = OfficeLocation.objects.filter(
                company=company, is_active=True
            )
            self.fields['manager'].queryset = EmployeeProfile.objects.filter(
                company=company
            ).exclude(role='employee')
        else:
            self.fields['office_location'].queryset = OfficeLocation.objects.none()
            self.fields['manager'].queryset = EmployeeProfile.objects.none()

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError('Username already exists.')
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email:
            if User.objects.filter(email=email).exists():
                raise forms.ValidationError('Email already registered.')
        return email

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')

        if password1 and password2 and password1 != password2:
            self.add_error('password2', 'Passwords do not match.')

        # NEW: enforce Django password validators
        if password1:
            try:
                validate_password(password1)
            except forms.ValidationError as exc:
                self.add_error('password1', exc)

        return cleaned_data

    def save(self, employee_id=None, company=None, commit=True):
        if company is None:
            raise ValueError("EmployeeForm.save() requires company=")
        if not employee_id:
            raise ValueError("EmployeeForm.save() requires employee_id=")

        user = User.objects.create_user(
            username=self.cleaned_data['username'],
            email=self.cleaned_data.get('email') or '',
            password=self.cleaned_data['password1'],
        )

        profile = EmployeeProfile.objects.create(
            user=user,
            employee_id=employee_id,
            company=company,
            full_name=self.cleaned_data['full_name'],
            date_of_birth=self.cleaned_data.get('date_of_birth'),
            date_of_joining=self.cleaned_data.get('date_of_joining'),
            designation=self.cleaned_data.get('designation', ''),
            department=self.cleaned_data.get('department', ''),
            phone=self.cleaned_data.get('phone', ''),
            address=self.cleaned_data.get('address', ''),
            # ── NEW: previously dropped fields ──
            role=self.cleaned_data['role'],
            attendance_type=self.cleaned_data['attendance_type'],
            office_location=self.cleaned_data.get('office_location'),
            manager=self.cleaned_data.get('manager'),
        )
        return profile
        

class ForgotPasswordForm(forms.Form):
    """Just the identifier — we never reveal if it exists."""
    identifier = forms.CharField(
        max_length=150,
        label='Employee ID / Username',
        widget=forms.TextInput(attrs={
            'placeholder': 'Employee ID or Username',
            'autocomplete': 'off',
            'autofocus': True,
        }),
    )

    def clean_identifier(self):
        return self.cleaned_data['identifier'].strip()



class SetNewPasswordForm(forms.Form):
    """HR Admin uses this to set the new password."""
    password1 = forms.CharField(
        label='New Password',
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
    )
    password2 = forms.CharField(
        label='Confirm New Password',
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('password1')
        p2 = cleaned.get('password2')

        if p1 and p2 and p1 != p2:
            self.add_error('password2', "Passwords do not match.")

        if p1:
            try:
                validate_password(p1, user=self.user)
            except forms.ValidationError as exc:
                self.add_error('password1', exc)

        return cleaned