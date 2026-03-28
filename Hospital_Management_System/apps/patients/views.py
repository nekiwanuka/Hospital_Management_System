from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from apps.admission.models import Admission
from apps.billing.models import Invoice
from apps.consultation.models import Consultation
from apps.core.permissions import (
    branch_queryset_for_user,
    module_permission_required,
    role_required,
)
from apps.laboratory.models import LabRequest
from apps.patients.forms import PatientForm
from apps.patients.models import Patient
from apps.radiology.models import ImagingRequest, RadiologyNotification
from apps.referrals.models import Referral
from apps.triage.models import TriageRecord


@login_required
@role_required(
    "receptionist",
    "nurse",
    "doctor",
    "triage_officer",
    "lab_technician",
    "radiology_technician",
    "radiologist",
    "pharmacist",
    "cashier",
    "system_admin",
    "director",
)
@module_permission_required("patients", "view")
def index(request):
    queryset = branch_queryset_for_user(
        request.user, Patient.objects.select_related("branch").order_by("-created_at")
    )
    query = request.GET.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(patient_id__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(phone__icontains=query)
        )

    paginator = Paginator(queryset, 5)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "patients/index.html",
        {
            "patients": page_obj.object_list,
            "page_obj": page_obj,
            "query": query,
        },
    )


def _get_patient_for_user_or_404(user, pk):
    patient = Patient.objects.select_related("branch").filter(pk=pk).first()
    if not patient:
        raise Http404("Patient not found")
    scoped = branch_queryset_for_user(user, Patient.objects.filter(pk=pk))
    if not scoped.exists():
        raise Http404("Patient not found")
    return patient


@login_required
@role_required("receptionist", "nurse", "doctor", "system_admin", "director")
@module_permission_required("patients", "create")
def create(request):
    if request.method == "POST":
        form = PatientForm(request.POST)
        if form.is_valid():
            if not request.user.branch_id:
                form.add_error(None, "Your user account has no branch assigned.")
                return render(
                    request,
                    "patients/form.html",
                    {
                        "form": form,
                        "page_title": "Register Patient",
                        "submit_label": "Create Patient",
                    },
                )
            patient = form.save(commit=False)
            patient.branch = request.user.branch
            patient.save()
            return redirect("patients:detail", pk=patient.pk)
    else:
        form = PatientForm()

    return render(
        request,
        "patients/form.html",
        {
            "form": form,
            "page_title": "Register Patient",
            "submit_label": "Create Patient",
        },
    )


@login_required
@role_required(
    "receptionist",
    "nurse",
    "doctor",
    "triage_officer",
    "lab_technician",
    "radiology_technician",
    "radiologist",
    "pharmacist",
    "cashier",
    "system_admin",
    "director",
)
@module_permission_required("patients", "view")
def detail(request, pk):
    patient = _get_patient_for_user_or_404(request.user, pk)
    return_to = (request.GET.get("return_to") or "").strip()
    if return_to and (
        not return_to.startswith("/")
        or not url_has_allowed_host_and_scheme(
            return_to,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        )
    ):
        return_to = ""

    history_only = (request.GET.get("history_only") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }

    can_edit_patient = request.user.role in {"receptionist", "system_admin", "director"}
    can_initiate_visit = request.user.role in {
        "receptionist",
        "nurse",
        "system_admin",
        "director",
    }

    medical_history = {
        "triage_records": TriageRecord.objects.filter(patient=patient).order_by(
            "-date"
        )[:20],
        "consultations": Consultation.objects.filter(patient=patient).order_by(
            "-created_at"
        )[:20],
        "lab_requests": LabRequest.objects.filter(patient=patient).order_by("-date")[
            :20
        ],
        "invoices": Invoice.objects.filter(patient=patient).order_by("-created_at")[
            :20
        ],
        "admissions": Admission.objects.filter(patient=patient).order_by(
            "-admission_date"
        )[:20],
        "referrals": Referral.objects.filter(patient=patient).order_by(
            "-referral_date"
        )[:20],
        "radiology_requests": branch_queryset_for_user(
            request.user,
            ImagingRequest.objects.select_related("result", "requested_by")
            .filter(patient=patient)
            .order_by("-date_requested"),
        )[:20],
        "radiology_notifications": branch_queryset_for_user(
            request.user,
            RadiologyNotification.objects.select_related("imaging_request", "recipient")
            .filter(imaging_request__patient=patient)
            .order_by("-created_at"),
        )[:20],
    }
    return render(
        request,
        "patients/detail.html",
        {
            "patient": patient,
            "medical_history": medical_history,
            "delete_object_type": "Patient",
            "delete_object_id": patient.pk,
            "delete_object_label": f"{patient.first_name} {patient.last_name}",
            "delete_next_url": request.path,
            "return_to": return_to,
            "history_only": history_only,
            "show_patient_actions": not history_only,
            "can_edit_patient": can_edit_patient,
            "can_initiate_visit": can_initiate_visit,
        },
    )


@login_required
@role_required("receptionist", "system_admin", "director")
@module_permission_required("patients", "update")
def edit(request, pk):
    patient = _get_patient_for_user_or_404(request.user, pk)

    if request.method == "POST":
        form = PatientForm(request.POST, instance=patient)
        if form.is_valid():
            updated_patient = form.save(commit=False)
            updated_patient.branch = patient.branch
            updated_patient.save()
            return redirect("patients:detail", pk=updated_patient.pk)
    else:
        form = PatientForm(instance=patient)

    return render(
        request,
        "patients/form.html",
        {
            "form": form,
            "patient": patient,
            "page_title": "Edit Patient",
            "submit_label": "Save Changes",
        },
    )
