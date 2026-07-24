from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
import os
from urllib.parse import quote
from xml.sax.saxutils import escape

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q, Sum
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .access import (
    ACTION_CREATE,
    ACTION_READ,
    ACTION_UPDATE,
    PROCUREMENT_GROUP,
    TRANSPORT_GROUP,
    can_edit_requisition,
    has_any_module_access,
    has_module_access,
    has_only_requisition_access,
    user_in_groups,
)
from .forms import (
    ApplicationSettingForm,
    BusinessClientForm,
    CommercialDocumentForm,
    DirectPurchaseOrderForm,
    ExpatriateForm,
    ExpatriateVisaForm,
    FinancialRecordForm,
    FuelAssetForm,
    FuelIssueForm,
    FuelStockBatchForm,
    ManagedUserForm,
    ModuleAccessFormSet,
    PurchaseInquiryForm,
    PurchaseOrderForm,
    PurchaseReceiptForm,
    RequisitionForm,
    RequisitionItemFormSet,
    SupplierForm,
    SupplierInvoiceForm,
    TransportAttachmentForm,
    TransportCustomerOrderFormSet,
    TransportGovernmentChargeForm,
    TransportRecordForm,
    TransportTransitCostForm,
    TransportTransitPointFormSet,
    VisaEmbassyForm,
)
from .i18n import normalize_language, translate
from .models import (
    ApplicationSetting,
    BusinessClient,
    CommercialDocument,
    Expatriate,
    ExpatriateVisa,
    FinancialRecord,
    FuelAsset,
    FuelIssue,
    FuelStockBatch,
    PurchaseInquiry,
    PurchaseOrder,
    Requisition,
    RequisitionItem,
    Supplier,
    TransportCustomerInvoice,
    TransportRecord,
    UserModuleAccess,
    VisaEmbassy,
)

LIST_RESULTS_LIMIT = 5
REPORT_QUANT = Decimal("0.01")


def module_not_found(request, exception=None, unknown_path=""):
    return render(request, "operations/module_not_found.html", status=404)


from .services import (
    generate_transport_customer_invoices,
    sync_transport_procurement_status,
)


def access_required(module, action):
    return user_passes_test(
        lambda user: has_module_access(user, module, action), login_url="login"
    )


def superuser_required(view_func):
    return user_passes_test(
        lambda user: user.is_authenticated and user.is_superuser, login_url="login"
    )(view_func)


def procurement_required(view_func):
    return user_passes_test(
        lambda user: has_any_module_access(user, [UserModuleAccess.Module.PROCUREMENT])
        or user_in_groups(user, [PROCUREMENT_GROUP])
    )(view_func)


def transport_required(view_func):
    return user_passes_test(
        lambda user: has_any_module_access(user, [UserModuleAccess.Module.TRANSPORT])
        or user_in_groups(user, [TRANSPORT_GROUP])
    )(view_func)


def fuel_required(view_func):
    return user_passes_test(
        lambda user: has_module_access(user, UserModuleAccess.Module.FUEL, ACTION_READ),
        login_url="login",
    )(view_func)


def visa_required(view_func):
    return user_passes_test(
        lambda user: has_module_access(
            user, UserModuleAccess.Module.VISAS, ACTION_READ
        ),
        login_url="login",
    )(view_func)


def requisition_item_data(formset):
    return [form.cleaned_data for form in formset.forms if form.cleaned_data]


def sync_requisition_summary(requisition, item_data):
    requisition.item_description = "\n".join(
        f"{item['description']} ({item['pieces']} pcs)" for item in item_data
    )
    requisition.quantity = sum(
        (Decimal(item["pieces"]) for item in item_data), Decimal("0")
    )


def sync_uploaded_requisition_summary(requisition):
    requisition.item_description = "Uploaded requisition document"
    requisition.quantity = Decimal("0")


def requisition_has_content(requisition, item_data):
    return bool(item_data) or bool(requisition.uploaded_document)


def refresh_requisition_procurement_status(requisition):
    if requisition.status in [
        Requisition.Status.IN_TRANSPORT,
        Requisition.Status.DELIVERED,
    ]:
        return
    requisition = Requisition.objects.prefetch_related(
        "items__purchase_inquiries__purchase_orders",
        "inquiries__purchase_orders",
    ).get(pk=requisition.pk)
    items = list(requisition.items.all())
    if items:
        any_inquiry = any(item.purchase_inquiries.all() for item in items)
        all_purchased = all(
            requisition_item_ordered_quantity(item) >= Decimal(item.pieces)
            for item in items
        )
    else:
        inquiries = list(requisition.inquiries.all())
        any_inquiry = bool(inquiries)
        all_purchased = bool(inquiries) and all(
            inquiry.purchase_orders.all() for inquiry in inquiries
        )

    if all_purchased:
        next_status = Requisition.Status.PURCHASED
    elif any_inquiry:
        next_status = Requisition.Status.INQUIRIES_SENT
    else:
        next_status = Requisition.Status.ACCEPTED

    if requisition.status != next_status:
        requisition.status = next_status
        requisition.save(update_fields=["status", "updated_at"])


def friendly_requisition_status(status):
    if status == Requisition.Status.ACCEPTED:
        return "Accepted"
    if status == Requisition.Status.IN_TRANSPORT:
        return "In delivery"
    return dict(Requisition.Status.choices).get(status, status)


def requisition_item_ordered_quantity(item):
    total = Decimal("0")
    for inquiry in item.purchase_inquiries.all():
        if inquiry.purchase_orders.all():
            total += inquiry.quantity
    return total


def procurement_split_items(query=None, search_date=None, limit=None):
    queryset = RequisitionItem.objects.filter(
        requisition__status__in=[
            Requisition.Status.ACCEPTED,
            Requisition.Status.INQUIRIES_SENT,
        ]
    )
    if query:
        queryset = queryset.filter(
            Q(requisition__requisition_number__icontains=query)
            | Q(requisition__requesting_company__icontains=query)
            | Q(description__icontains=query)
            | Q(requisition__requester__username__icontains=query)
        )
    if search_date:
        queryset = queryset.filter(
            Q(requisition__created_at__date=search_date)
            | Q(requisition__updated_at__date=search_date)
        )
    items = list(
        queryset.select_related(
            "requisition", "requisition__requester"
        ).prefetch_related(
            "purchase_inquiries__supplier", "purchase_inquiries__purchase_orders"
        )
    )
    ready_items = []
    for item in items:
        item.ordered_quantity = requisition_item_ordered_quantity(item)
        item.remaining_quantity = max(
            Decimal(item.pieces) - item.ordered_quantity, Decimal("0")
        )
        if item.remaining_quantity:
            ready_items.append(item)
    if limit:
        return ready_items[:limit]
    return ready_items


def request_language(request):
    return normalize_language(
        request.GET.get("language")
        or request.session.get("active_language")
        or request.COOKIES.get("active_language")
        or ApplicationSetting.load().default_language
    )


def pdf_font_name(language="en"):
    if normalize_language(language) == "en":
        return "Helvetica"
    font_name = "ArialUnicodeMS"
    if font_name not in pdfmetrics.getRegisteredFontNames():
        font_path = "C:/Windows/Fonts/ARIALUNI.TTF"
        if os.path.exists(font_path):
            pdfmetrics.registerFont(TTFont(font_name, font_path))
        else:
            return "Helvetica"
    return font_name


def purchase_order_message(order, language="en"):
    return (
        f"{translate('Purchase Order', language)} {order.order_number}\n"
        f"{translate('Supplier', language)}: {order.supplier.name}\n"
        f"{translate('Requisition', language)}: {order.inquiry.requisition.requisition_number}\n"
        f"{translate('Item', language)}: {order.inquiry.description}\n"
        f"{translate('Quantity', language)}: {order.inquiry.quantity}\n"
        f"{translate('Amount', language)}: {order.amount}\n"
        f"{translate('Date', language)}: {order.order_date}"
    )


def purchase_order_document(order, language="en"):
    supplier_lines = [
        f"{translate('Supplier', language)}: {order.supplier.name}",
        f"{translate('Contact', language)}: {order.supplier.contact_person or '-'}",
        f"{translate('Email', language)}: {order.supplier.email or '-'}",
        f"{translate('Phone', language)}: {order.supplier.phone or '-'}",
    ]
    order_lines = [
        f"{translate('Purchase Order', language)}: {order.order_number}",
        f"{translate('Requisition', language)}: {order.inquiry.requisition.requisition_number}",
        f"{translate('Order date', language)}: {order.order_date}",
        f"{translate('Prepared by', language)}: {order.created_by}",
        "",
        translate("Order details", language).upper(),
        f"{translate('Description', language)}: {order.inquiry.description}",
        f"{translate('Quantity', language)}: {order.inquiry.quantity}",
        f"{translate('Amount', language)}: {order.amount}",
        "",
        translate("Supplier message", language).upper(),
        order.supplier_message or purchase_order_message(order, language),
    ]
    return "\n".join(
        [
            f"MINING ERP {translate('Purchase Order', language).upper()}",
            "",
            *supplier_lines,
            "",
            *order_lines,
        ]
    )


def pdf_text(value):
    return escape(str(value or "-"))


def purchase_order_pdf(order, language="en"):
    rl_config.invariant = 1
    app_setting = ApplicationSetting.load()
    language = normalize_language(language)
    message = order.supplier_message or purchase_order_message(order, language)
    font_name = pdf_font_name(language)
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(
        "PurchaseOrderBody",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#14201b"),
    )
    muted_style = ParagraphStyle(
        "PurchaseOrderMuted",
        parent=body_style,
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#68736c"),
    )
    label_style = ParagraphStyle(
        "PurchaseOrderLabel",
        parent=muted_style,
        fontName=font_name,
        fontSize=7,
        leading=9,
        textColor=colors.HexColor("#68736c"),
    )
    title_style = ParagraphStyle(
        "PurchaseOrderTitle",
        parent=styles["Title"],
        alignment=TA_RIGHT,
        fontName=font_name,
        fontSize=22,
        leading=24,
        textColor=colors.HexColor("#14201b"),
    )
    story = []

    if app_setting.logo:
        try:
            brand_mark = Image(app_setting.logo.path, width=18 * mm, height=18 * mm)
        except Exception:
            brand_mark = Paragraph(
                pdf_text(app_setting.application_name[:2]).upper(), title_style
            )
    else:
        brand_mark = Paragraph(
            pdf_text(app_setting.application_name[:2]).upper(), title_style
        )

    brand = Table(
        [
            [
                brand_mark,
                Paragraph(
                    f"<b>{pdf_text(app_setting.application_name)}</b><br/>{pdf_text(app_setting.address or '')}",
                    body_style,
                ),
            ]
        ],
        colWidths=[22 * mm, 82 * mm],
    )
    title = Paragraph(
        f"{pdf_text(translate('Purchase Order', language))}<br/><font size='14'>{pdf_text(order.order_number)}</font><br/><font size='8'>{pdf_text(order.order_date)}</font>",
        title_style,
    )
    header = Table([[brand, title]], colWidths=[104 * mm, 70 * mm])
    header.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -1), 1.2, colors.HexColor("#14201b")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    story.extend([header, Spacer(1, 10)])

    supplier_card = Table(
        [
            [Paragraph(pdf_text(translate("Supplier", language)).upper(), label_style)],
            [Paragraph(f"<b>{pdf_text(order.supplier.name)}</b>", body_style)],
            [Paragraph(pdf_text(order.supplier.contact_person), body_style)],
            [Paragraph(pdf_text(order.supplier.email), body_style)],
            [Paragraph(pdf_text(order.supplier.phone), body_style)],
        ]
    )
    reference_card = Table(
        [
            [
                Paragraph(
                    pdf_text(translate("Order Reference", language)).upper(),
                    label_style,
                )
            ],
            [
                Paragraph(
                    f"{pdf_text(translate('Requisition', language))}: <b>{pdf_text(order.inquiry.requisition.requisition_number)}</b>",
                    body_style,
                )
            ],
            [
                Paragraph(
                    f"{pdf_text(translate('Prepared by', language))}: <b>{pdf_text(order.created_by)}</b>",
                    body_style,
                )
            ],
            [
                Paragraph(
                    f"{pdf_text(translate('Delivery', language))}: <b>{pdf_text(order.get_delivery_method_display())}</b>",
                    body_style,
                )
            ],
            [
                Paragraph(
                    f"{pdf_text(translate('Status', language))}: <b>{pdf_text(order.get_status_display())}</b>",
                    body_style,
                )
            ],
        ]
    )
    cards = Table([[supplier_card, reference_card]], colWidths=[84 * mm, 84 * mm])
    cards.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#dbe2dd")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dbe2dd")),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f9faf7")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("PADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    story.extend([cards, Spacer(1, 12)])

    item_table = Table(
        [
            [
                translate("Description", language),
                translate("Quantity", language),
                translate("Amount", language),
            ],
            [
                pdf_text(order.inquiry.description),
                f"{order.inquiry.quantity:.2f}",
                f"{order.amount:.2f}",
            ],
            ["", translate("Total", language), f"{order.amount:.2f}"],
        ],
        colWidths=[104 * mm, 32 * mm, 32 * mm],
    )
    item_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#14201b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), font_name),
                ("FONTNAME", (0, -1), (-1, -1), font_name),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dbe2dd")),
                ("PADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story.extend([item_table, Spacer(1, 12)])
    story.append(
        Paragraph(
            pdf_text(translate("Supplier message", language)).upper(), label_style
        )
    )
    story.append(Paragraph(pdf_text(message).replace("\n", "<br/>"), body_style))
    story.append(Spacer(1, 24))
    signatures = Table(
        [
            [
                translate("Authorized Signature", language),
                translate("Supplier Acknowledgement", language),
            ]
        ],
        colWidths=[78 * mm, 78 * mm],
    )
    signatures.setStyle(
        TableStyle(
            [
                ("LINEABOVE", (0, 0), (-1, 0), 0.8, colors.HexColor("#14201b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#68736c")),
                ("FONTNAME", (0, 0), (-1, 0), font_name),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
            ]
        )
    )
    story.append(signatures)
    document.build(story)
    return buffer.getvalue()


def purchase_order_pdf_response(order, as_attachment=False, language="en"):
    response = HttpResponse(
        purchase_order_pdf(order, language), content_type="application/pdf"
    )
    disposition = "attachment" if as_attachment else "inline"
    response["Content-Disposition"] = (
        f'{disposition}; filename="{order.order_number}.pdf"'
    )
    return response


def requester_company_default(user):
    return user.get_full_name() or user.username


def requisition_pdf(requisition, language="en"):
    rl_config.invariant = 1
    app_setting = ApplicationSetting.load()
    language = normalize_language(language)
    font_name = pdf_font_name(language)
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(
        "RequisitionBody",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#14201b"),
    )
    label_style = ParagraphStyle(
        "RequisitionLabel",
        parent=body_style,
        fontSize=7,
        leading=9,
        textColor=colors.HexColor("#68736c"),
    )
    title_style = ParagraphStyle(
        "RequisitionTitle",
        parent=styles["Title"],
        alignment=TA_RIGHT,
        fontName=font_name,
        fontSize=22,
        leading=24,
        textColor=colors.HexColor("#14201b"),
    )
    story = []

    if app_setting.logo:
        try:
            brand_mark = Image(app_setting.logo.path, width=18 * mm, height=18 * mm)
        except Exception:
            brand_mark = Paragraph(
                pdf_text(app_setting.application_name[:2]).upper(), title_style
            )
    else:
        brand_mark = Paragraph(
            pdf_text(app_setting.application_name[:2]).upper(), title_style
        )

    brand = Table(
        [
            [
                brand_mark,
                Paragraph(
                    f"<b>{pdf_text(app_setting.application_name)}</b><br/>{pdf_text(app_setting.address or '')}",
                    body_style,
                ),
            ]
        ],
        colWidths=[22 * mm, 82 * mm],
    )
    title = Paragraph(
        f"{pdf_text(translate('Requisition', language))}<br/><font size='14'>{pdf_text(requisition.requisition_number)}</font><br/><font size='8'>{pdf_text(requisition.created_at.date())}</font>",
        title_style,
    )
    header = Table([[brand, title]], colWidths=[104 * mm, 70 * mm])
    header.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -1), 1.2, colors.HexColor("#14201b")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    story.extend([header, Spacer(1, 10)])

    reference_card = Table(
        [
            [Paragraph("REQUESTER COPY", label_style)],
            [
                Paragraph(
                    f"Company / site: <b>{pdf_text(requisition.requester_label)}</b>",
                    body_style,
                )
            ],
            [
                Paragraph(
                    f"Submitted by: <b>{pdf_text(requisition.requester)}</b>",
                    body_style,
                )
            ],
            [
                Paragraph(
                    f"Status: <b>{pdf_text(requisition.get_status_display())}</b>",
                    body_style,
                )
            ],
            [
                Paragraph(
                    f"Urgency: <b>{pdf_text('Urgent' if requisition.urgent else 'Not urgent')}</b>",
                    body_style,
                )
            ],
        ]
    )
    reference_card.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#dbe2dd")),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f9faf7")),
                ("PADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    story.extend([reference_card, Spacer(1, 12)])

    rows = [["Item", "Pieces"]]
    items = list(requisition.items.all())
    if items:
        rows.extend([[pdf_text(item.description), item.pieces] for item in items])
    else:
        rows.append([pdf_text(requisition.item_description), requisition.quantity])
    rows.append(["Total", requisition.total_pieces])
    item_table = Table(rows, colWidths=[134 * mm, 34 * mm])
    item_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#14201b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dbe2dd")),
                ("PADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story.extend([item_table, Spacer(1, 18)])
    story.append(
        Paragraph(
            "This copy can be kept by the requesting mining center and shared manually with procurement.",
            body_style,
        )
    )
    document.build(story)
    return buffer.getvalue()


def requisition_pdf_response(requisition, as_attachment=False, language="en"):
    response = HttpResponse(
        requisition_pdf(requisition, language), content_type="application/pdf"
    )
    disposition = "attachment" if as_attachment else "inline"
    response["Content-Disposition"] = (
        f'{disposition}; filename="{requisition.requisition_number}.pdf"'
    )
    return response


def transport_invoice_message(invoice):
    return (
        f"Transport Invoice {invoice.invoice_number}\n"
        f"Customer: {invoice.customer_name}\n"
        f"Transit: {invoice.transport.transit_number}\n"
        f"Vehicle: {invoice.transport.vehicle}\n"
        f"Route: {invoice.transport.origin} to {invoice.transport.destination}\n"
        f"Total: {invoice.total_amount:.2f}"
    )


def transport_invoice_pdf(invoice, language="en"):
    rl_config.invariant = 1
    language = normalize_language(language)
    app_setting = ApplicationSetting.load()
    font_name = pdf_font_name(language)
    bold_font_name = font_name if language != "en" else "Helvetica-Bold"
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(
        "TransportInvoiceBody",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#14201b"),
    )
    label_style = ParagraphStyle(
        "TransportInvoiceLabel",
        parent=body_style,
        fontName=bold_font_name,
        fontSize=7,
        leading=9,
        textColor=colors.HexColor("#68736c"),
    )
    title_style = ParagraphStyle(
        "TransportInvoiceTitle",
        parent=styles["Title"],
        alignment=TA_RIGHT,
        fontName=bold_font_name,
        fontSize=22,
        leading=24,
        textColor=colors.HexColor("#14201b"),
    )
    if app_setting.logo:
        try:
            brand_mark = Image(app_setting.logo.path, width=18 * mm, height=18 * mm)
        except Exception:
            brand_mark = Paragraph(
                pdf_text(app_setting.application_name[:2]).upper(), title_style
            )
    else:
        brand_mark = Paragraph(
            pdf_text(app_setting.application_name[:2]).upper(), title_style
        )

    brand = Table(
        [
            [
                brand_mark,
                Paragraph(
                    f"<b>{pdf_text(app_setting.application_name)}</b><br/>{pdf_text(app_setting.address or '')}",
                    body_style,
                ),
            ]
        ],
        colWidths=[22 * mm, 82 * mm],
    )
    title = Paragraph(
        f"{pdf_text(translate('Transport Invoice', language))}<br/><font size='14'>{pdf_text(invoice.invoice_number)}</font><br/><font size='8'>{pdf_text(invoice.invoice_date)}</font>",
        title_style,
    )
    header = Table([[brand, title]], colWidths=[104 * mm, 70 * mm])
    header.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -1), 1.2, colors.HexColor("#14201b")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    customer = invoice.customer_order
    details = Table(
        [
            [
                Table(
                    [
                        [
                            Paragraph(
                                pdf_text(translate("Customer", language)).upper(),
                                label_style,
                            )
                        ],
                        [
                            Paragraph(
                                f"<b>{pdf_text(invoice.customer_name)}</b>", body_style
                            )
                        ],
                        [
                            Paragraph(
                                f"{pdf_text(translate('Cargo', language))}: {pdf_text(customer.cargo_description)}",
                                body_style,
                            )
                        ],
                        [
                            Paragraph(
                                f"{pdf_text(translate('Loading', language))}: {pdf_text(customer.loading_point or invoice.transport.origin)}",
                                body_style,
                            )
                        ],
                        [
                            Paragraph(
                                f"{pdf_text(translate('Offloading', language))}: {pdf_text(customer.offloading_point or invoice.transport.destination)}",
                                body_style,
                            )
                        ],
                    ]
                ),
                Table(
                    [
                        [
                            Paragraph(
                                pdf_text(translate("Transit", language)).upper(),
                                label_style,
                            )
                        ],
                        [
                            Paragraph(
                                f"{pdf_text(translate('Transit', language))}: <b>{pdf_text(invoice.transport.transit_number)}</b>",
                                body_style,
                            )
                        ],
                        [
                            Paragraph(
                                f"{pdf_text(translate('Vehicle', language))}: <b>{pdf_text(invoice.transport.vehicle)}</b>",
                                body_style,
                            )
                        ],
                        [
                            Paragraph(
                                f"{pdf_text(translate('Route', language))}: {pdf_text(invoice.transport.origin)} {pdf_text(translate('to', language))} {pdf_text(invoice.transport.destination)}",
                                body_style,
                            )
                        ],
                        [
                            Paragraph(
                                f"{pdf_text(translate('Status', language))}: <b>{pdf_text(translate(invoice.get_status_display(), language))}</b>",
                                body_style,
                            )
                        ],
                    ]
                ),
            ]
        ],
        colWidths=[84 * mm, 84 * mm],
    )
    details.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#dbe2dd")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dbe2dd")),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f9faf7")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("PADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    rows = [
        [
            translate("Type", language),
            translate("Description", language),
            translate("Amount", language),
        ]
    ]
    for line in invoice.lines.all():
        rows.append(
            [
                translate(line.get_line_type_display(), language),
                line.description,
                f"{line.amount:.2f}",
            ]
        )
    rows.append(["", translate("Total", language), f"{invoice.total_amount:.2f}"])
    lines = Table(rows, colWidths=[44 * mm, 92 * mm, 32 * mm])
    lines.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#14201b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), bold_font_name),
                ("FONTNAME", (0, -1), (-1, -1), bold_font_name),
                ("ALIGN", (2, 1), (2, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dbe2dd")),
                ("PADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    signatures = Table(
        [
            [
                translate("Prepared by", language),
                translate("Customer Acknowledgement", language),
            ]
        ],
        colWidths=[78 * mm, 78 * mm],
    )
    signatures.setStyle(
        TableStyle(
            [
                ("LINEABOVE", (0, 0), (-1, 0), 0.8, colors.HexColor("#14201b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#68736c")),
                ("FONTNAME", (0, 0), (-1, 0), bold_font_name),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
            ]
        )
    )
    document.build(
        [
            header,
            Spacer(1, 10),
            details,
            Spacer(1, 12),
            lines,
            Spacer(1, 24),
            signatures,
        ]
    )
    return buffer.getvalue()


def transport_invoice_pdf_response(invoice, as_attachment=False, language="en"):
    response = HttpResponse(
        transport_invoice_pdf(invoice, language), content_type="application/pdf"
    )
    disposition = "attachment" if as_attachment else "inline"
    response["Content-Disposition"] = (
        f'{disposition}; filename="{invoice.invoice_number}.pdf"'
    )
    return response


def digits_only(value):
    return "".join(character for character in value if character.isdigit())


def access_initial(user=None):
    access_by_module = {}
    if user and user.pk:
        access_by_module = {
            access.module: access for access in user.module_access.all()
        }
    initial = []
    for module, _label in UserModuleAccess.Module.choices:
        access = access_by_module.get(module)
        initial.append(
            {
                "module": module,
                "can_create": bool(access and access.can_create),
                "can_read": bool(access and access.can_read),
                "can_update": bool(access and access.can_update),
                "can_delete": bool(access and access.can_delete),
            }
        )
    return initial


def access_rows(formset):
    labels = dict(UserModuleAccess.Module.choices)
    rows = []
    for form in formset:
        module = form["module"].value()
        rows.append({"form": form, "label": labels.get(module, module)})
    return rows


def save_access_rows(user, formset):
    for form in formset:
        data = form.cleaned_data
        module = data["module"]
        allowed = {
            "can_create": data.get("can_create", False),
            "can_read": data.get("can_read", False),
            "can_update": data.get("can_update", False),
            "can_delete": data.get("can_delete", False),
        }
        if any(allowed.values()):
            UserModuleAccess.objects.update_or_create(
                user=user,
                module=module,
                defaults=allowed,
            )
        else:
            UserModuleAccess.objects.filter(user=user, module=module).delete()


@require_GET
def language_change(request):
    language = request.GET.get("language", ApplicationSetting.Language.ENGLISH)
    allowed_languages = {code for code, _label in ApplicationSetting.Language.choices}
    if language not in allowed_languages:
        language = ApplicationSetting.load().default_language
    next_url = (
        request.GET.get("next") or request.META.get("HTTP_REFERER") or "dashboard"
    )
    request.session["active_language"] = language
    response = redirect(next_url)
    response.set_cookie("active_language", language, max_age=60 * 60 * 24 * 365)
    return response


@login_required
def dashboard(request):
    if has_only_requisition_access(request.user):
        if has_module_access(
            request.user, UserModuleAccess.Module.REQUISITIONS, ACTION_CREATE
        ):
            return redirect("requisition_create")
        return redirect("requisition_list")

    transport_records = TransportRecord.objects.select_related(
        "supplier", "requisition"
    ).prefetch_related("customer_orders__purchase_order", "transit_points")[
        :LIST_RESULTS_LIMIT
    ]
    context = {
        "requisition_count": Requisition.objects.count(),
        "submitted_count": Requisition.objects.filter(
            status=Requisition.Status.SUBMITTED
        ).count(),
        "inquiry_count": PurchaseInquiry.objects.count(),
        "transport_count": TransportRecord.objects.count(),
        "commercial_document_count": CommercialDocument.objects.count(),
        "financial_record_count": FinancialRecord.objects.count(),
        "status_breakdown": Requisition.objects.values("status")
        .annotate(total=Count("id"))
        .order_by("status"),
        "latest_requisitions": Requisition.objects.select_related(
            "requester"
        ).prefetch_related("items")[:LIST_RESULTS_LIMIT],
        "latest_transport_records": transport_records,
        "latest_commercial_documents": CommercialDocument.objects.select_related(
            "client", "transport", "purchase_order", "requisition"
        )[:LIST_RESULTS_LIMIT],
        "transport_total": sum(
            (record.total_cost for record in transport_records), Decimal("0")
        ),
    }
    return render(request, "operations/dashboard.html", context)


@login_required
@access_required(UserModuleAccess.Module.REQUISITIONS, ACTION_READ)
def requisition_list(request):
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "all").strip() or "all"
    allowed_statuses = {code for code, _label in Requisition.Status.choices}
    queryset = Requisition.objects.select_related("requester").prefetch_related("items")
    can_see_all = (
        request.user.is_superuser
        or has_module_access(
            request.user, UserModuleAccess.Module.REQUISITIONS, ACTION_UPDATE
        )
        or user_in_groups(request.user, [PROCUREMENT_GROUP, TRANSPORT_GROUP])
    )
    if not can_see_all:
        queryset = queryset.filter(requester=request.user)
    base_queryset = queryset
    if query:
        queryset = queryset.filter(
            Q(requisition_number__icontains=query)
            | Q(requesting_company__icontains=query)
            | Q(item_description__icontains=query)
            | Q(items__description__icontains=query)
            | Q(requester__username__icontains=query)
        ).distinct()
    if status in allowed_statuses:
        queryset = queryset.filter(status=status)

    requisitions = list(queryset[:LIST_RESULTS_LIMIT])
    for requisition in requisitions:
        requisition.can_edit_pending = can_edit_requisition(request.user, requisition)
        requisition.display_status = friendly_requisition_status(requisition.status)

    status_counts = {
        row["status"]: row["total"]
        for row in base_queryset.values("status").annotate(total=Count("id"))
    }
    return render(
        request,
        "operations/requisition_list.html",
        {
            "requisitions": requisitions,
            "query": query,
            "status": status,
            "status_options": [
                (code, friendly_requisition_status(code))
                for code, label in Requisition.Status.choices
            ],
            "total_count": base_queryset.count(),
            "submitted_count": status_counts.get(Requisition.Status.SUBMITTED, 0),
            "accepted_count": status_counts.get(Requisition.Status.ACCEPTED, 0)
            + status_counts.get(Requisition.Status.INQUIRIES_SENT, 0),
            "purchased_count": status_counts.get(Requisition.Status.PURCHASED, 0),
        },
    )


@login_required
@access_required(UserModuleAccess.Module.REQUISITIONS, ACTION_CREATE)
def requisition_create(request):
    form = RequisitionForm(
        request.POST or None,
        request.FILES or None,
        initial={"requesting_company": requester_company_default(request.user)},
    )
    item_formset = RequisitionItemFormSet(request.POST or None, prefix="items")
    if request.method == "POST" and form.is_valid() and item_formset.is_valid():
        item_data = requisition_item_data(item_formset)
        requisition = form.save(commit=False)
        requisition.requester = request.user
        if not requisition.requesting_company:
            requisition.requesting_company = requester_company_default(request.user)
        if not requisition_has_content(requisition, item_data):
            form.add_error(
                "uploaded_document",
                "Upload a prepared requisition or add at least one item line.",
            )
        else:
            if item_data:
                sync_requisition_summary(requisition, item_data)
            else:
                sync_uploaded_requisition_summary(requisition)
            requisition.save()
            for item in item_data:
                requisition.items.create(
                    description=item["description"], pieces=item["pieces"]
                )
            messages.success(
                request, f"Requisition {requisition.requisition_number} submitted."
            )
            if has_only_requisition_access(request.user):
                return redirect("requisition_create")
            if has_module_access(
                request.user, UserModuleAccess.Module.REQUISITIONS, ACTION_READ
            ):
                return redirect("requisition_list")
            return redirect("dashboard")
    pending_requisitions = []
    if has_module_access(
        request.user, UserModuleAccess.Module.REQUISITIONS, ACTION_READ
    ):
        pending_requisitions = list(
            Requisition.objects.filter(
                requester=request.user, status=Requisition.Status.SUBMITTED
            )
            .prefetch_related("items")
            .order_by("-created_at")[:LIST_RESULTS_LIMIT]
        )
        for requisition in pending_requisitions:
            requisition.can_edit_pending = can_edit_requisition(
                request.user, requisition
            )
            requisition.display_status = friendly_requisition_status(requisition.status)
    return render(
        request,
        "operations/requisition_form.html",
        {
            "title": "New Requisition",
            "subtitle": "Add one or more items, their number of pieces, and urgency.",
            "form": form,
            "item_formset": item_formset,
            "action_label": "Submit requisition",
            "cancel_url": "requisition_list",
            "multipart": True,
            "pending_requisitions": pending_requisitions,
            "is_requester_landing": has_only_requisition_access(request.user),
        },
    )


@login_required
@access_required(UserModuleAccess.Module.REQUISITIONS, ACTION_READ)
def requisition_edit(request, pk):
    requisition = get_object_or_404(
        Requisition.objects.prefetch_related("items"), pk=pk
    )
    if not can_edit_requisition(request.user, requisition):
        raise PermissionDenied("This requisition can no longer be edited.")

    form = RequisitionForm(
        request.POST or None, request.FILES or None, instance=requisition
    )
    item_formset = RequisitionItemFormSet(
        request.POST or None, instance=requisition, prefix="items"
    )
    if request.method == "POST" and form.is_valid() and item_formset.is_valid():
        item_data = requisition_item_data(item_formset)
        requisition = form.save(commit=False)
        if not requisition_has_content(requisition, item_data):
            form.add_error(
                "uploaded_document",
                "Upload a prepared requisition or add at least one item line.",
            )
        else:
            if item_data:
                sync_requisition_summary(requisition, item_data)
            else:
                sync_uploaded_requisition_summary(requisition)
            requisition.save()
            requisition.items.all().delete()
            for item in item_data:
                requisition.items.create(
                    description=item["description"], pieces=item["pieces"]
                )
            messages.success(
                request, f"Requisition {requisition.requisition_number} updated."
            )
            return redirect("requisition_list")

    return render(
        request,
        "operations/requisition_form.html",
        {
            "title": f"Edit {requisition.requisition_number}",
            "subtitle": "You can edit this requisition until procurement accepts it.",
            "form": form,
            "item_formset": item_formset,
            "action_label": "Save requisition",
            "cancel_url": "requisition_list",
            "multipart": True,
        },
    )


@login_required
def requisition_download(request, pk):
    requisition = get_object_or_404(
        Requisition.objects.select_related("requester").prefetch_related("items"), pk=pk
    )
    can_download = (
        request.user.is_superuser
        or requisition.requester_id == request.user.id
        or has_module_access(
            request.user, UserModuleAccess.Module.REQUISITIONS, ACTION_UPDATE
        )
        or user_in_groups(request.user, [PROCUREMENT_GROUP])
    )
    if not can_download:
        raise PermissionDenied("You cannot download this requisition copy.")
    return requisition_pdf_response(
        requisition, as_attachment=True, language=request_language(request)
    )


@login_required
def requisition_uploaded_document_download(request, pk):
    requisition = get_object_or_404(
        Requisition.objects.select_related("requester"), pk=pk
    )
    can_download = (
        request.user.is_superuser
        or requisition.requester_id == request.user.id
        or has_module_access(
            request.user, UserModuleAccess.Module.REQUISITIONS, ACTION_UPDATE
        )
        or user_in_groups(request.user, [PROCUREMENT_GROUP])
    )
    if not can_download:
        raise PermissionDenied("You cannot download this requisition file.")
    if not requisition.uploaded_document:
        raise PermissionDenied("This requisition does not have an uploaded document.")
    return FileResponse(
        requisition.uploaded_document.open("rb"),
        as_attachment=True,
        filename=os.path.basename(requisition.uploaded_document.name),
    )


@access_required(UserModuleAccess.Module.SUPPLIERS, ACTION_CREATE)
def supplier_create(request):
    form = SupplierForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        supplier = form.save()
        messages.success(request, f"Supplier {supplier.name} saved.")
        return redirect("procurement_dashboard")
    return render(
        request,
        "operations/form_page.html",
        {
            "title": "New Supplier",
            "subtitle": "Register a supplier before sending a purchase inquiry.",
            "form": form,
            "action_label": "Save supplier",
            "cancel_url": "procurement_dashboard",
        },
    )


@login_required
@access_required(UserModuleAccess.Module.FUEL, ACTION_READ)
def fuel_dashboard(request):
    assets = FuelAsset.objects.all()[:LIST_RESULTS_LIMIT]
    batches = FuelStockBatch.objects.prefetch_related("issues")[:LIST_RESULTS_LIMIT]
    issues = FuelIssue.objects.select_related("batch", "asset", "issued_by")[
        :LIST_RESULTS_LIMIT
    ]
    all_batches = FuelStockBatch.objects.prefetch_related("issues")
    total_received = sum(
        (batch.litres_received for batch in all_batches),
        Decimal("0"),
    )
    total_available = sum(
        (batch.available_litres for batch in all_batches), Decimal("0")
    )
    total_issued = total_received - total_available
    return render(
        request,
        "operations/fuel_dashboard.html",
        {
            "assets": assets,
            "batches": batches,
            "issues": issues,
            "total_received": total_received,
            "total_available": total_available,
            "total_issued": total_issued,
        },
    )


@login_required
@access_required(UserModuleAccess.Module.FUEL, ACTION_READ)
def fuel_batch_balance(request):
    query = request.GET.get("q", "").strip()
    fuel_type = request.GET.get("fuel_type", "all").strip() or "all"
    storage_method = request.GET.get("storage", "all").strip() or "all"
    allowed_fuel_types = {code for code, _label in FuelStockBatch.FuelType.choices}
    allowed_storage_methods = {
        code for code, _label in FuelStockBatch.StorageMethod.choices
    }
    batches = FuelStockBatch.objects.prefetch_related("issues").order_by(
        "-received_date", "-created_at"
    )
    if query:
        batches = batches.filter(
            Q(batch_number__icontains=query)
            | Q(source_truck__icontains=query)
            | Q(notes__icontains=query)
        )
    if fuel_type in allowed_fuel_types:
        batches = batches.filter(fuel_type=fuel_type)
    if storage_method in allowed_storage_methods:
        batches = batches.filter(storage_method=storage_method)
    all_matching_batches = list(batches)
    batches = all_matching_batches[:LIST_RESULTS_LIMIT]
    total_received = sum(
        (batch.litres_received for batch in all_matching_batches),
        Decimal("0"),
    )
    total_available = sum(
        (batch.available_litres for batch in all_matching_batches), Decimal("0")
    )
    total_issued = total_received - total_available
    return render(
        request,
        "operations/fuel_batch_balance.html",
        {
            "batches": batches,
            "query": query,
            "fuel_type": fuel_type,
            "fuel_type_options": FuelStockBatch.FuelType.choices,
            "storage": storage_method,
            "storage_options": FuelStockBatch.StorageMethod.choices,
            "matching_count": len(all_matching_batches),
            "total_received": total_received,
            "total_available": total_available,
            "total_issued": total_issued,
        },
    )


@login_required
@access_required(UserModuleAccess.Module.FUEL, ACTION_CREATE)
def fuel_asset_create(request):
    form = FuelAssetForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        asset = form.save()
        messages.success(request, f"Fleet asset {asset.name} saved.")
        return redirect("fuel_dashboard")
    return render(
        request,
        "operations/form_page.html",
        {
            "title": "New fleet / machine",
            "subtitle": "Register a machine, vehicle, generator, or mine line before issuing fuel.",
            "form": form,
            "action_label": "Save asset",
            "cancel_url": "fuel_dashboard",
        },
    )


@login_required
@access_required(UserModuleAccess.Module.FUEL, ACTION_CREATE)
def fuel_batch_create(request):
    form = FuelStockBatchForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        batch = form.save(commit=False)
        batch.created_by = request.user
        batch.save()
        messages.success(request, f"Fuel batch {batch.batch_number} received.")
        return redirect("fuel_dashboard")
    return render(
        request,
        "operations/form_page.html",
        {
            "title": "Receive fuel on site",
            "subtitle": "Record the truck delivery, storage method, and total litres before any field refills happen.",
            "form": form,
            "action_label": "Save fuel batch",
            "cancel_url": "fuel_dashboard",
        },
    )


@login_required
@access_required(UserModuleAccess.Module.FUEL, ACTION_CREATE)
def fuel_issue_create(request):
    form = FuelIssueForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        issue = form.save(commit=False)
        issue.issued_by = request.user
        issue.full_clean()
        issue.save()
        messages.success(
            request,
            f"Fuel issue {issue.issue_number} saved and deducted from {issue.batch.batch_number}.",
        )
        return redirect("fuel_dashboard")
    return render(
        request,
        "operations/form_page.html",
        {
            "title": "Record fuel refill",
            "subtitle": "Deduct litres from a batch and record the responsible driver/operator, gauge readings, and route/location.",
            "form": form,
            "action_label": "Save refill",
            "cancel_url": "fuel_dashboard",
        },
    )


def visa_alert_groups(visas):
    groups = {
        "Expired": [],
        "3 days": [],
        "7 days": [],
        "14 days": [],
        "30 days": [],
        "Valid": [],
    }
    for visa in visas:
        groups[visa.expiry_alert].append(visa)
    return groups


@login_required
@access_required(UserModuleAccess.Module.VISAS, ACTION_READ)
def visa_dashboard(request):
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "all").strip() or "all"
    allowed_statuses = {code for code, _label in ExpatriateVisa.RenewalStatus.choices}
    visa_queryset = ExpatriateVisa.objects.select_related(
        "expatriate", "embassy", "created_by"
    ).order_by("expiry_date")
    if query:
        visa_queryset = visa_queryset.filter(
            Q(record_number__icontains=query)
            | Q(visa_reference__icontains=query)
            | Q(expatriate__first_name__icontains=query)
            | Q(expatriate__last_name__icontains=query)
            | Q(expatriate__passport_number__icontains=query)
            | Q(embassy__name__icontains=query)
        )
    if status in allowed_statuses:
        visa_queryset = visa_queryset.filter(renewal_status=status)
    visas = list(visa_queryset[:LIST_RESULTS_LIMIT])
    alert_groups = visa_alert_groups(visas)
    expats = Expatriate.objects.all()[:LIST_RESULTS_LIMIT]
    embassies = VisaEmbassy.objects.all()[:LIST_RESULTS_LIMIT]
    return render(
        request,
        "operations/visa_dashboard.html",
        {
            "visas": visas,
            "expats": expats,
            "embassies": embassies,
            "alert_groups": alert_groups,
            "query": query,
            "status": status,
            "status_options": ExpatriateVisa.RenewalStatus.choices,
            "matching_count": visa_queryset.count(),
            "expired_count": len(alert_groups["Expired"]),
            "due_3_count": len(alert_groups["3 days"]),
            "due_7_count": len(alert_groups["7 days"]),
            "due_14_count": len(alert_groups["14 days"]),
            "due_30_count": len(alert_groups["30 days"]),
        },
    )


@login_required
@access_required(UserModuleAccess.Module.VISAS, ACTION_READ)
def visa_alerts(request):
    query = request.GET.get("q", "").strip()
    alert = request.GET.get("alert", "all").strip() or "all"
    visas = ExpatriateVisa.objects.select_related("expatriate", "embassy").order_by(
        "expiry_date"
    )
    if query:
        visas = visas.filter(
            Q(record_number__icontains=query)
            | Q(visa_reference__icontains=query)
            | Q(expatriate__first_name__icontains=query)
            | Q(expatriate__last_name__icontains=query)
            | Q(expatriate__passport_number__icontains=query)
            | Q(embassy__name__icontains=query)
        )
    visas = list(visas)
    if alert != "all":
        visas = [visa for visa in visas if visa.expiry_alert == alert]
    visas = visas[:LIST_RESULTS_LIMIT]
    alert_options = ["Expired", "3 days", "7 days", "14 days", "30 days", "Valid"]
    return render(
        request,
        "operations/visa_alerts.html",
        {
            "alert_groups": visa_alert_groups(visas),
            "query": query,
            "alert": alert,
            "alert_options": alert_options,
            "matching_count": len(visas),
        },
    )


@login_required
@access_required(UserModuleAccess.Module.VISAS, ACTION_CREATE)
def visa_embassy_create(request):
    form = VisaEmbassyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        embassy = form.save()
        messages.success(request, f"Embassy {embassy.name} saved.")
        return redirect("visa_dashboard")
    return render(
        request,
        "operations/form_page.html",
        {
            "title": "New embassy / authority",
            "subtitle": "Record contact details, renewal requirements, fees, and processing time.",
            "form": form,
            "action_label": "Save embassy",
            "cancel_url": "visa_dashboard",
        },
    )


@login_required
@access_required(UserModuleAccess.Module.VISAS, ACTION_CREATE)
def expatriate_create(request):
    form = ExpatriateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        expatriate = form.save(commit=False)
        expatriate.created_by = request.user
        expatriate.save()
        messages.success(request, f"Expatriate {expatriate.full_name} saved.")
        return redirect("visa_dashboard")
    return render(
        request,
        "operations/form_page.html",
        {
            "title": "New expatriate",
            "subtitle": "Record passport, role, contact, department, and emergency details before adding visa validity.",
            "form": form,
            "action_label": "Save expatriate",
            "cancel_url": "visa_dashboard",
        },
    )


@login_required
@access_required(UserModuleAccess.Module.VISAS, ACTION_CREATE)
def expatriate_visa_create(request):
    form = ExpatriateVisaForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        visa = form.save(commit=False)
        visa.created_by = request.user
        visa.save()
        messages.success(
            request,
            f"Visa record {visa.record_number} saved for {visa.expatriate.full_name}.",
        )
        return redirect("visa_dashboard")
    return render(
        request,
        "operations/form_page.html",
        {
            "title": "New visa record",
            "subtitle": "Record validity, expiry, embassy, requirements, fees, status, and reminder owner.",
            "form": form,
            "action_label": "Save visa",
            "cancel_url": "visa_dashboard",
        },
    )


@access_required(UserModuleAccess.Module.PROCUREMENT, ACTION_READ)
def procurement_dashboard(request):
    query = request.GET.get("q", "").strip()
    date_value = request.GET.get("date", "").strip()
    search_date = parse_date(date_value) if date_value else None
    phase = request.GET.get("phase", "all").strip() or "all"
    visible_limit = 5
    allowed_phases = {"all", "review", "orders", "invoices", "receipts", "complete"}
    if phase not in allowed_phases:
        phase = "all"

    submitted_requisitions = Requisition.objects.filter(
        status=Requisition.Status.SUBMITTED
    )
    accepted_requisitions = Requisition.objects.filter(
        status__in=[Requisition.Status.ACCEPTED, Requisition.Status.INQUIRIES_SENT]
    )
    inquiries_waiting_invoice = PurchaseInquiry.objects.filter(
        status=PurchaseInquiry.Status.SENT
    )
    inquiries_ready_for_order = PurchaseInquiry.objects.filter(
        status=PurchaseInquiry.Status.INVOICE_LOADED
    )
    orders_waiting_receipts = PurchaseOrder.objects.filter(
        status=PurchaseOrder.Status.ISSUED
    )
    recent_purchase_orders = PurchaseOrder.objects.all()

    if query:
        submitted_requisitions = submitted_requisitions.filter(
            Q(requisition_number__icontains=query)
            | Q(item_description__icontains=query)
            | Q(requester__username__icontains=query)
        )
        accepted_requisitions = accepted_requisitions.filter(
            Q(requisition_number__icontains=query)
            | Q(item_description__icontains=query)
            | Q(requester__username__icontains=query)
        )
        inquiries_waiting_invoice = inquiries_waiting_invoice.filter(
            Q(inquiry_number__icontains=query)
            | Q(requisition__requisition_number__icontains=query)
            | Q(supplier__name__icontains=query)
            | Q(description__icontains=query)
        )
        inquiries_ready_for_order = inquiries_ready_for_order.filter(
            Q(inquiry_number__icontains=query)
            | Q(requisition__requisition_number__icontains=query)
            | Q(supplier__name__icontains=query)
            | Q(description__icontains=query)
        )
        orders_waiting_receipts = orders_waiting_receipts.filter(
            Q(order_number__icontains=query)
            | Q(inquiry__inquiry_number__icontains=query)
            | Q(supplier__name__icontains=query)
            | Q(inquiry__description__icontains=query)
        )
        recent_purchase_orders = recent_purchase_orders.filter(
            Q(order_number__icontains=query)
            | Q(inquiry__inquiry_number__icontains=query)
            | Q(supplier__name__icontains=query)
            | Q(inquiry__description__icontains=query)
            | Q(inquiry__requisition__requisition_number__icontains=query)
            | Q(inquiry__supplier_invoices__invoice_number__icontains=query)
            | Q(receipts__receipt_number__icontains=query)
        )
    if search_date:
        submitted_requisitions = submitted_requisitions.filter(
            Q(created_at__date=search_date) | Q(updated_at__date=search_date)
        )
        accepted_requisitions = accepted_requisitions.filter(
            Q(created_at__date=search_date) | Q(updated_at__date=search_date)
        )
        inquiries_waiting_invoice = inquiries_waiting_invoice.filter(
            Q(sent_at__date=search_date) | Q(created_at__date=search_date)
        )
        inquiries_ready_for_order = inquiries_ready_for_order.filter(
            Q(sent_at__date=search_date)
            | Q(created_at__date=search_date)
            | Q(supplier_invoices__invoice_date=search_date)
        )
        orders_waiting_receipts = orders_waiting_receipts.filter(
            Q(order_date=search_date) | Q(created_at__date=search_date)
        )
        recent_purchase_orders = recent_purchase_orders.filter(
            Q(order_date=search_date)
            | Q(created_at__date=search_date)
            | Q(receipts__receipt_date=search_date)
            | Q(inquiry__supplier_invoices__invoice_date=search_date)
        )

    context = {
        "submitted_requisitions": submitted_requisitions.select_related(
            "requester"
        ).prefetch_related("items")[:visible_limit],
        "items_ready_for_inquiry": procurement_split_items(
            query, search_date, visible_limit
        ),
        "accepted_requisitions": accepted_requisitions.select_related(
            "requester"
        ).prefetch_related("items")[:visible_limit],
        "inquiries_waiting_invoice": inquiries_waiting_invoice.select_related(
            "requisition", "requisition_item", "supplier"
        ).distinct()[:visible_limit],
        "inquiries_ready_for_order": inquiries_ready_for_order.select_related(
            "requisition", "requisition_item", "supplier"
        ).distinct()[:visible_limit],
        "orders_waiting_receipts": orders_waiting_receipts.select_related(
            "inquiry", "supplier"
        ).distinct()[:visible_limit],
        "recent_purchase_orders": recent_purchase_orders.select_related(
            "inquiry", "supplier", "inquiry__requisition", "inquiry__requisition_item"
        ).distinct()[:visible_limit],
        "suppliers": Supplier.objects.all()[:LIST_RESULTS_LIMIT],
        "query": query,
        "date_value": date_value,
        "phase": phase,
    }
    return render(request, "operations/procurement.html", context)


@access_required(UserModuleAccess.Module.PROCUREMENT, ACTION_READ)
def requisition_process_list(request):
    query = request.GET.get("q", "").strip()
    requisitions = Requisition.objects.select_related("requester").prefetch_related(
        "items__purchase_inquiries__supplier",
        "items__purchase_inquiries__supplier_invoices",
        "items__purchase_inquiries__purchase_orders__supplier",
        "items__purchase_inquiries__purchase_orders__receipts",
        "inquiries__supplier",
        "inquiries__supplier_invoices",
        "inquiries__purchase_orders__supplier",
        "inquiries__purchase_orders__receipts",
    )
    if query:
        requisitions = requisitions.filter(
            Q(requisition_number__icontains=query)
            | Q(requesting_company__icontains=query)
            | Q(item_description__icontains=query)
            | Q(items__description__icontains=query)
            | Q(requester__username__icontains=query)
            | Q(inquiries__inquiry_number__icontains=query)
            | Q(inquiries__supplier__name__icontains=query)
            | Q(inquiries__supplier_invoices__invoice_number__icontains=query)
            | Q(inquiries__supplier_invoices__supplier_name__icontains=query)
            | Q(inquiries__purchase_orders__order_number__icontains=query)
            | Q(inquiries__purchase_orders__supplier__name__icontains=query)
            | Q(inquiries__purchase_orders__receipts__receipt_number__icontains=query)
        ).distinct()
    requisitions = requisitions[:50]
    return render(
        request,
        "operations/requisition_process.html",
        {"requisitions": requisitions, "query": query},
    )


@access_required(UserModuleAccess.Module.REQUISITIONS, ACTION_UPDATE)
def procurement_requisition_review(request, pk):
    requisition = get_object_or_404(
        Requisition.objects.prefetch_related("items"), pk=pk
    )
    if requisition.status in [
        Requisition.Status.PURCHASED,
        Requisition.Status.IN_TRANSPORT,
        Requisition.Status.DELIVERED,
    ]:
        raise PermissionDenied(
            "This requisition has already moved past procurement review."
        )

    form = RequisitionForm(request.POST or None, instance=requisition)
    item_formset = RequisitionItemFormSet(
        request.POST or None, instance=requisition, prefix="items"
    )
    if request.method == "POST" and form.is_valid() and item_formset.is_valid():
        item_data = requisition_item_data(item_formset)
        requisition = form.save(commit=False)
        sync_requisition_summary(requisition, item_data)
        requisition.status = Requisition.Status.ACCEPTED
        requisition.save()
        requisition.items.all().delete()
        for item in item_data:
            requisition.items.create(
                description=item["description"], pieces=item["pieces"]
            )
        messages.success(
            request, f"{requisition.requisition_number} reviewed and accepted."
        )
        return redirect("procurement_dashboard")

    return render(
        request,
        "operations/requisition_form.html",
        {
            "title": f"Review {requisition.requisition_number}",
            "subtitle": "Review, edit, and accept the requester requisition before supplier purchase orders.",
            "form": form,
            "item_formset": item_formset,
            "action_label": "Save review and accept",
            "cancel_url": "procurement_dashboard",
        },
    )


@access_required(UserModuleAccess.Module.REQUISITIONS, ACTION_UPDATE)
@require_POST
def requisition_accept(request, pk):
    requisition = get_object_or_404(Requisition, pk=pk)
    requisition.status = Requisition.Status.ACCEPTED
    requisition.save(update_fields=["status", "updated_at"])
    messages.success(
        request, f"{requisition.requisition_number} accepted by procurement."
    )
    return redirect("procurement_dashboard")


@access_required(UserModuleAccess.Module.PURCHASE_ORDERS, ACTION_CREATE)
def item_purchase_order_create(request, item_id):
    item = get_object_or_404(
        RequisitionItem.objects.select_related("requisition"), pk=item_id
    )
    if item.requisition.status not in [
        Requisition.Status.ACCEPTED,
        Requisition.Status.INQUIRIES_SENT,
    ]:
        raise PermissionDenied(
            "Review and accept the requisition before creating purchase orders."
        )
    item = RequisitionItem.objects.prefetch_related(
        "purchase_inquiries__purchase_orders"
    ).get(pk=item.pk)
    ordered_quantity = requisition_item_ordered_quantity(item)
    remaining_quantity = max(Decimal(item.pieces) - ordered_quantity, Decimal("0"))
    if not remaining_quantity:
        messages.info(request, "This item has already been fully ordered.")
        return redirect("procurement_dashboard")

    form = DirectPurchaseOrderForm(
        request.POST or None,
        max_quantity=remaining_quantity,
        initial={
            "description": item.description,
            "quantity": remaining_quantity,
            "order_date": date.today(),
            "delivery_method": PurchaseOrder.DeliveryMethod.EMAIL,
        },
    )
    if request.method == "POST" and form.is_valid():
        supplier = form.resolve_supplier()
        inquiry = PurchaseInquiry.objects.create(
            requisition=item.requisition,
            requisition_item=item,
            supplier=supplier,
            description=form.cleaned_data["description"],
            quantity=form.cleaned_data["quantity"],
            status=PurchaseInquiry.Status.ORDERED,
            sent_at=timezone.now(),
            sent_by=request.user,
        )
        order = PurchaseOrder.objects.create(
            inquiry=inquiry,
            supplier=supplier,
            amount=form.cleaned_data["amount"],
            order_date=form.cleaned_data["order_date"],
            delivery_method=form.cleaned_data["delivery_method"],
            supplier_message=form.cleaned_data["supplier_message"],
            sent_at=timezone.now(),
            created_by=request.user,
        )
        if not order.supplier_message:
            order.supplier_message = purchase_order_message(order)
            order.save(update_fields=["supplier_message", "updated_at"])
        refresh_requisition_procurement_status(item.requisition)
        messages.success(
            request, f"Purchase order {order.order_number} created for {supplier.name}."
        )
        return redirect("purchase_order_detail", order_id=order.pk)

    return render(
        request,
        "operations/form_page.html",
        {
            "title": f"Create PO for {item.requisition.requisition_number}",
            "subtitle": f"Remaining quantity for this item: {remaining_quantity}. Split by item quantity or choose a different supplier.",
            "form": form,
            "action_label": "Create and prepare to send",
            "cancel_url": "procurement_dashboard",
        },
    )


@access_required(UserModuleAccess.Module.PURCHASE_INQUIRIES, ACTION_CREATE)
def inquiry_create(request, requisition_id):
    requisition = get_object_or_404(
        Requisition.objects.prefetch_related("items"), pk=requisition_id
    )
    if requisition.status not in [
        Requisition.Status.ACCEPTED,
        Requisition.Status.INQUIRIES_SENT,
    ]:
        raise PermissionDenied(
            "Accept the requisition before sending supplier inquiries."
        )
    form = PurchaseInquiryForm(
        request.POST or None,
        initial={
            "description": requisition.item_summary,
            "quantity": requisition.total_pieces,
        },
    )
    if request.method == "POST" and form.is_valid():
        inquiry = form.save(commit=False)
        inquiry.requisition = requisition
        inquiry.sent_by = request.user
        inquiry.status = PurchaseInquiry.Status.SENT
        inquiry.sent_at = timezone.now()
        inquiry.save()
        refresh_requisition_procurement_status(requisition)
        messages.success(
            request,
            f"Purchase inquiry {inquiry.inquiry_number} sent to {inquiry.supplier}.",
        )
        return redirect("procurement_dashboard")
    return render(
        request,
        "operations/form_page.html",
        {
            "title": f"Split {requisition.requisition_number} into inquiry",
            "subtitle": "Select supplier, confirm quantity, and send the inquiry.",
            "form": form,
            "action_label": "Send inquiry",
            "cancel_url": "procurement_dashboard",
        },
    )


@access_required(UserModuleAccess.Module.PURCHASE_INQUIRIES, ACTION_CREATE)
def item_inquiry_create(request, item_id):
    item = get_object_or_404(
        RequisitionItem.objects.select_related("requisition"), pk=item_id
    )
    if item.requisition.status not in [
        Requisition.Status.ACCEPTED,
        Requisition.Status.INQUIRIES_SENT,
    ]:
        raise PermissionDenied(
            "Accept the requisition before sending supplier inquiries."
        )
    form = PurchaseInquiryForm(
        request.POST or None,
        initial={"description": item.description, "quantity": item.pieces},
    )
    if request.method == "POST" and form.is_valid():
        inquiry = form.save(commit=False)
        inquiry.requisition = item.requisition
        inquiry.requisition_item = item
        inquiry.sent_by = request.user
        inquiry.status = PurchaseInquiry.Status.SENT
        inquiry.sent_at = timezone.now()
        inquiry.save()
        refresh_requisition_procurement_status(item.requisition)
        messages.success(
            request,
            f"Purchase inquiry {inquiry.inquiry_number} sent to {inquiry.supplier} for {item.description}.",
        )
        return redirect("procurement_dashboard")
    return render(
        request,
        "operations/form_page.html",
        {
            "title": f"Send {item.requisition.requisition_number} item to supplier",
            "subtitle": "Choose the supplier and confirm the item quantity for this purchase inquiry.",
            "form": form,
            "action_label": "Send inquiry to supplier",
            "cancel_url": "procurement_dashboard",
        },
    )


@access_required(UserModuleAccess.Module.SUPPLIER_INVOICES, ACTION_CREATE)
def supplier_invoice_upload(request, inquiry_id):
    inquiry = get_object_or_404(
        PurchaseInquiry.objects.select_related("requisition", "supplier"), pk=inquiry_id
    )
    form = SupplierInvoiceForm(
        request.POST or None,
        request.FILES or None,
        inquiry=inquiry,
        initial={"invoice_date": date.today()},
    )
    if request.method == "POST" and form.is_valid():
        supplier = form.resolve_supplier()
        invoice = form.save(commit=False)
        invoice.inquiry = inquiry
        invoice.requisition_number = inquiry.requisition.requisition_number
        invoice.supplier = supplier
        invoice.supplier_name = supplier.name
        invoice.uploaded_by = request.user
        invoice.save()
        if inquiry.supplier_id != supplier.id:
            inquiry.supplier = supplier
        inquiry.status = PurchaseInquiry.Status.INVOICE_LOADED
        inquiry.save(update_fields=["supplier", "status", "updated_at"])
        messages.success(
            request,
            f"Invoice {invoice.invoice_number} loaded against {inquiry.inquiry_number}.",
        )
        return redirect("procurement_dashboard")
    return render(
        request,
        "operations/form_page.html",
        {
            "title": f"Load supplier invoice for {inquiry.inquiry_number}",
            "subtitle": "Attach the supplier invoice against this purchase inquiry.",
            "form": form,
            "action_label": "Upload invoice",
            "cancel_url": "procurement_dashboard",
            "multipart": True,
        },
    )


@access_required(UserModuleAccess.Module.PURCHASE_ORDERS, ACTION_CREATE)
def purchase_order_create(request, inquiry_id):
    inquiry = get_object_or_404(PurchaseInquiry, pk=inquiry_id)
    latest_invoice = inquiry.supplier_invoices.first()
    form = PurchaseOrderForm(
        request.POST or None,
        initial={
            "amount": latest_invoice.amount if latest_invoice else None,
            "order_date": date.today(),
        },
    )
    if request.method == "POST" and form.is_valid():
        order = form.save(commit=False)
        order.inquiry = inquiry
        order.supplier = inquiry.supplier
        order.created_by = request.user
        order.save()
        inquiry.status = PurchaseInquiry.Status.ORDERED
        inquiry.save(update_fields=["status", "updated_at"])
        refresh_requisition_procurement_status(inquiry.requisition)
        messages.success(request, f"Purchase order {order.order_number} created.")
        return redirect("purchase_order_detail", order_id=order.pk)
    return render(
        request,
        "operations/form_page.html",
        {
            "title": f"Create purchase order for {inquiry.inquiry_number}",
            "subtitle": "Confirm the purchase amount after supplier invoice review.",
            "form": form,
            "action_label": "Create purchase order",
            "cancel_url": "procurement_dashboard",
        },
    )


@access_required(UserModuleAccess.Module.PURCHASE_ORDERS, ACTION_READ)
def purchase_order_detail(request, order_id):
    order = get_object_or_404(
        PurchaseOrder.objects.select_related(
            "supplier",
            "inquiry",
            "inquiry__requisition",
            "inquiry__requisition_item",
            "created_by",
        ),
        pk=order_id,
    )
    language = request_language(request)
    message = order.supplier_message or purchase_order_message(order, language)
    email_subject = f"Purchase Order {order.order_number}"
    email = order.supplier.email
    phone = digits_only(order.supplier.phone)
    context = {
        "order": order,
        "message": message,
        "email_url": (
            f"mailto:{email}?subject={quote(email_subject)}&body={quote(message)}"
            if email
            else ""
        ),
        "whatsapp_url": f"https://wa.me/{phone}?text={quote(message)}" if phone else "",
        "document": purchase_order_document(order, language),
    }
    return render(request, "operations/purchase_order_detail.html", context)


@access_required(UserModuleAccess.Module.PURCHASE_ORDERS, ACTION_READ)
def purchase_order_download(request, order_id):
    order = get_object_or_404(
        PurchaseOrder.objects.select_related(
            "supplier",
            "inquiry",
            "inquiry__requisition",
            "created_by",
        ),
        pk=order_id,
    )
    return purchase_order_pdf_response(
        order, as_attachment=True, language=request_language(request)
    )


@access_required(UserModuleAccess.Module.PURCHASE_ORDERS, ACTION_READ)
def purchase_order_print(request, order_id):
    order = get_object_or_404(
        PurchaseOrder.objects.select_related(
            "supplier",
            "inquiry",
            "inquiry__requisition",
            "created_by",
        ),
        pk=order_id,
    )
    return purchase_order_pdf_response(
        order, as_attachment=False, language=request_language(request)
    )


@access_required(UserModuleAccess.Module.PROCUREMENT, ACTION_READ)
def procurement_workflow_manual(request):
    return render(request, "operations/procurement_workflow_manual.html")


@access_required(UserModuleAccess.Module.PURCHASE_RECEIPTS, ACTION_CREATE)
def purchase_receipt_upload(request, order_id):
    order = get_object_or_404(PurchaseOrder, pk=order_id)
    form = PurchaseReceiptForm(
        request.POST or None,
        request.FILES or None,
        initial={"receipt_date": date.today()},
    )
    if request.method == "POST" and form.is_valid():
        receipt = form.save(commit=False)
        receipt.purchase_order = order
        receipt.uploaded_by = request.user
        receipt.save()
        order.status = PurchaseOrder.Status.RECEIPT_UPLOADED
        order.save(update_fields=["status", "updated_at"])
        messages.success(
            request,
            f"Receipt {receipt.receipt_number} uploaded for {order.order_number}.",
        )
        return redirect("procurement_dashboard")
    return render(
        request,
        "operations/form_page.html",
        {
            "title": f"Upload receipt for {order.order_number}",
            "subtitle": "Attach the purchase receipt before loading for transportation.",
            "form": form,
            "action_label": "Upload receipt",
            "cancel_url": "procurement_dashboard",
            "multipart": True,
        },
    )


@access_required(UserModuleAccess.Module.TRANSPORT, ACTION_READ)
def transport_list(request):
    query = request.GET.get("q", "").strip()
    date_value = request.GET.get("date", "").strip()
    search_date = parse_date(date_value) if date_value else None
    records = TransportRecord.objects.select_related(
        "supplier", "requisition", "purchase_order"
    ).prefetch_related("customer_orders__purchase_order", "transit_points")
    if query:
        records = records.filter(
            Q(transport_number__icontains=query)
            | Q(transit_number__icontains=query)
            | Q(vehicle__icontains=query)
            | Q(driver__icontains=query)
            | Q(origin__icontains=query)
            | Q(destination__icontains=query)
            | Q(supplier__name__icontains=query)
            | Q(requisition__requisition_number__icontains=query)
            | Q(customer_orders__customer_name__icontains=query)
            | Q(customer_orders__purchase_order__order_number__icontains=query)
        ).distinct()
    if search_date:
        records = records.filter(date=search_date)
    matching_count = records.count()
    records = records[:LIST_RESULTS_LIMIT]
    return render(
        request,
        "operations/transport_list.html",
        {
            "records": records,
            "query": query,
            "date_value": date_value,
            "matching_count": matching_count,
        },
    )


@access_required(UserModuleAccess.Module.TRANSPORT, ACTION_CREATE)
def transport_create(request):
    record = TransportRecord()
    form = TransportRecordForm(
        request.POST or None, instance=record, initial={"date": date.today()}
    )
    order_formset = TransportCustomerOrderFormSet(
        request.POST or None, instance=record, prefix="customer_orders"
    )
    transit_formset = TransportTransitPointFormSet(
        request.POST or None, instance=record, prefix="transit_points"
    )
    if (
        request.method == "POST"
        and form.is_valid()
        and order_formset.is_valid()
        and transit_formset.is_valid()
    ):
        record = form.save(commit=False)
        record.created_by = request.user
        record.save()
        order_formset.instance = record
        order_formset.save()
        transit_formset.instance = record
        transit_formset.save()
        sync_transport_procurement_status(record)
        messages.success(
            request, f"Transport record {record.transport_number} created."
        )
        return redirect("transport_detail", pk=record.pk)
    return render(
        request,
        "operations/transport_form.html",
        {
            "form": form,
            "order_formset": order_formset,
            "transit_formset": transit_formset,
        },
    )


@access_required(UserModuleAccess.Module.TRANSPORT, ACTION_READ)
def transport_detail(request, pk):
    record = get_object_or_404(
        TransportRecord.objects.select_related(
            "supplier", "requisition", "purchase_order"
        ).prefetch_related(
            "customer_orders__purchase_order",
            "transit_points",
            "transit_costs__customer_order",
            "customer_invoices__lines",
        ),
        pk=pk,
    )
    return render(
        request,
        "operations/transport_detail.html",
        {
            "record": record,
            "attachment_form": TransportAttachmentForm(),
            "charge_form": TransportGovernmentChargeForm(),
            "transit_cost_form": TransportTransitCostForm(transport=record),
        },
    )


@access_required(UserModuleAccess.Module.TRANSPORT, ACTION_CREATE)
@require_POST
def transport_invoices_generate(request, pk):
    record = get_object_or_404(
        TransportRecord.objects.prefetch_related("customer_orders", "transit_points"),
        pk=pk,
    )
    invoices = generate_transport_customer_invoices(record, request.user)
    messages.success(request, f"Generated {len(invoices)} customer invoice(s).")
    return redirect("transport_detail", pk=record.pk)


@access_required(UserModuleAccess.Module.TRANSPORT, ACTION_READ)
def transport_invoice_list(request):
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "all").strip() or "all"
    date_value = request.GET.get("date", "").strip()
    search_date = parse_date(date_value) if date_value else None
    allowed_statuses = {
        code for code, _label in TransportCustomerInvoice.Status.choices
    }
    invoices = TransportCustomerInvoice.objects.select_related(
        "transport", "customer_order", "generated_by"
    ).prefetch_related("lines")
    if query:
        invoices = invoices.filter(
            Q(invoice_number__icontains=query)
            | Q(customer_name__icontains=query)
            | Q(transport__transport_number__icontains=query)
            | Q(transport__transit_number__icontains=query)
            | Q(transport__vehicle__icontains=query)
        )
    if status in allowed_statuses:
        invoices = invoices.filter(status=status)
    if search_date:
        invoices = invoices.filter(invoice_date=search_date)
    matching_count = invoices.count()
    invoices = invoices[:LIST_RESULTS_LIMIT]
    return render(
        request,
        "operations/transport_invoice_list.html",
        {
            "invoices": invoices,
            "query": query,
            "status": status,
            "status_options": TransportCustomerInvoice.Status.choices,
            "date_value": date_value,
            "matching_count": matching_count,
        },
    )


@access_required(UserModuleAccess.Module.TRANSPORT, ACTION_READ)
def transport_invoice_detail(request, invoice_id):
    invoice = get_object_or_404(
        TransportCustomerInvoice.objects.select_related(
            "transport", "customer_order", "generated_by"
        ).prefetch_related("lines"),
        pk=invoice_id,
    )
    message = transport_invoice_message(invoice)
    whatsapp_url = f"https://wa.me/?text={quote(message)}"
    return render(
        request,
        "operations/transport_invoice_detail.html",
        {"invoice": invoice, "whatsapp_url": whatsapp_url},
    )


@access_required(UserModuleAccess.Module.TRANSPORT, ACTION_READ)
def transport_invoice_download(request, invoice_id):
    invoice = get_object_or_404(
        TransportCustomerInvoice.objects.select_related(
            "transport", "customer_order", "generated_by"
        ).prefetch_related("lines"),
        pk=invoice_id,
    )
    return transport_invoice_pdf_response(
        invoice, as_attachment=True, language=request_language(request)
    )


@access_required(UserModuleAccess.Module.TRANSPORT, ACTION_READ)
def transport_invoice_print(request, invoice_id):
    invoice = get_object_or_404(
        TransportCustomerInvoice.objects.select_related(
            "transport", "customer_order", "generated_by"
        ).prefetch_related("lines"),
        pk=invoice_id,
    )
    return transport_invoice_pdf_response(
        invoice, as_attachment=False, language=request_language(request)
    )


@access_required(UserModuleAccess.Module.TRANSPORT, ACTION_READ)
def transport_billing_manual(request):
    return render(request, "operations/transport_billing_manual.html")


@access_required(UserModuleAccess.Module.TRANSPORT, ACTION_CREATE)
def transport_delivery_note_create(request, pk):
    if not has_module_access(
        request.user, UserModuleAccess.Module.COMMERCIAL_DOCUMENTS, ACTION_CREATE
    ):
        raise PermissionDenied
    record = get_object_or_404(
        TransportRecord.objects.select_related(
            "requisition", "purchase_order", "supplier"
        ),
        pk=pk,
    )
    first_customer = record.customer_orders.order_by("loading_sequence", "id").first()
    initial = {
        "document_type": CommercialDocument.DocumentType.DELIVERY_NOTE,
        "status": CommercialDocument.Status.ISSUED,
        "title": f"Delivery note for {record.transit_number}",
        "transport": record,
        "requisition": record.requisition,
        "purchase_order": record.purchase_order,
        "supplier": record.supplier,
        "business_reference": record.transit_number,
        "document_date": date.today(),
        "new_client_name": first_customer.customer_name if first_customer else "",
        "description": record.customer_names_summary,
        "notes": f"Route: {record.origin} to {record.destination}. Vehicle: {record.vehicle}. Driver: {record.driver}.",
    }
    return commercial_document_form(
        request,
        initial=initial,
        title="New Transport Delivery Note",
        cancel_url="transport_detail",
        cancel_kwargs={"pk": record.pk},
    )


@access_required(UserModuleAccess.Module.TRANSPORT, ACTION_CREATE)
@require_POST
def transport_attachment_add(request, pk):
    record = get_object_or_404(TransportRecord, pk=pk)
    form = TransportAttachmentForm(request.POST, request.FILES)
    if form.is_valid():
        attachment = form.save(commit=False)
        attachment.transport = record
        attachment.uploaded_by = request.user
        attachment.save()
        messages.success(request, "Transport attachment uploaded.")
    else:
        messages.error(
            request,
            "Attachment could not be uploaded. Check the selected document and file.",
        )
    return redirect("transport_detail", pk=record.pk)


@access_required(UserModuleAccess.Module.TRANSPORT, ACTION_CREATE)
@require_POST
def transport_charge_add(request, pk):
    record = get_object_or_404(TransportRecord, pk=pk)
    form = TransportGovernmentChargeForm(request.POST)
    if form.is_valid():
        charge = form.save(commit=False)
        charge.transport = record
        charge.save()
        messages.success(request, f"Custom government charge {charge.name} added.")
    else:
        messages.error(request, "Custom government charge could not be added.")
    return redirect("transport_detail", pk=record.pk)


@access_required(UserModuleAccess.Module.TRANSPORT, ACTION_CREATE)
@require_POST
def transport_transit_cost_add(request, pk):
    record = get_object_or_404(TransportRecord, pk=pk)
    form = TransportTransitCostForm(request.POST, transport=record)
    if form.is_valid():
        cost = form.save(commit=False)
        cost.transport = record
        cost.save()
        messages.success(request, f"Transit cost {cost.display_name} added.")
    else:
        messages.error(
            request, "Transit cost could not be added. Check the cost details."
        )
    return redirect("transport_detail", pk=record.pk)


@access_required(UserModuleAccess.Module.TRANSPORT_REPORTS, ACTION_READ)
def transport_reports(request):
    records = list(
        TransportRecord.objects.select_related(
            "supplier", "requisition", "purchase_order"
        ).prefetch_related(
            "customer_orders__purchase_order__supplier", "transit_points"
        )
    )
    total_cost = sum((record.total_cost for record in records), Decimal("0"))
    total_tons = sum(
        (record.weight_tons or Decimal("0") for record in records), Decimal("0")
    )
    total_cbm = sum((record.cbm for record in records), Decimal("0"))

    def report_money(value):
        return Decimal(value or 0).quantize(REPORT_QUANT, rounding=ROUND_HALF_UP)

    def grouped_total(label_getter, value_getter=lambda record: record.total_cost):
        grouped = defaultdict(Decimal)
        for record in records:
            grouped[label_getter(record)] += value_getter(record)
        return [
            {"label": label, "total": report_money(total)}
            for label, total in sorted(grouped.items())
        ]

    context = {
        "cost_per_shipment": [
            {"label": record.transport_number, "total": report_money(record.total_cost)}
            for record in records
        ],
        "revenue_per_transit": grouped_total(
            lambda record: record.transit_number or record.transport_number,
            lambda record: record.invoice_revenue_total,
        ),
        "profit_per_transit": grouped_total(
            lambda record: record.transit_number or record.transport_number,
            lambda record: record.transit_profit,
        ),
        "cost_per_supplier": grouped_total(
            lambda record: record.supplier_names_summary or "Unassigned"
        ),
        "cost_per_customer": grouped_total(
            lambda record: record.customer_names_summary or "Unassigned"
        ),
        "cost_by_destination": grouped_total(lambda record: record.destination),
        "cost_by_requisition": grouped_total(
            lambda record: (
                record.requisition.requisition_number
                if record.requisition
                else "Unassigned"
            )
        ),
        "cost_by_transit": grouped_total(
            lambda record: record.transit_number or "Unassigned"
        ),
        "cost_by_transit_point": grouped_total(
            lambda record: record.transit_points_summary or "Unassigned"
        ),
        "average_cost_per_ton": (
            report_money(total_cost / total_tons) if total_tons else None
        ),
        "average_cost_per_cbm": (
            report_money(total_cost / total_cbm) if total_cbm else None
        ),
    }
    return render(request, "operations/reports.html", context)


@access_required(UserModuleAccess.Module.COMMERCIAL_DOCUMENTS, ACTION_READ)
def commercial_document_list(request):
    query = request.GET.get("q", "").strip()
    document_type = request.GET.get("type", "all").strip() or "all"
    documents = CommercialDocument.objects.select_related(
        "client",
        "transport",
        "purchase_order",
        "requisition",
        "supplier",
        "created_by",
    )
    if query:
        documents = documents.filter(
            Q(document_number__icontains=query)
            | Q(title__icontains=query)
            | Q(client__name__icontains=query)
            | Q(client_name__icontains=query)
            | Q(transport__transit_number__icontains=query)
            | Q(transport__transport_number__icontains=query)
            | Q(purchase_order__order_number__icontains=query)
            | Q(requisition__requisition_number__icontains=query)
            | Q(business_reference__icontains=query)
        ).distinct()
    allowed_types = {code for code, _label in CommercialDocument.DocumentType.choices}
    if document_type in allowed_types:
        documents = documents.filter(document_type=document_type)
    matching_count = documents.count()
    documents = documents[:LIST_RESULTS_LIMIT]
    return render(
        request,
        "operations/commercial_document_list.html",
        {
            "documents": documents,
            "query": query,
            "document_type": document_type,
            "document_types": CommercialDocument.DocumentType.choices,
            "matching_count": matching_count,
        },
    )


@access_required(UserModuleAccess.Module.COMMERCIAL_DOCUMENTS, ACTION_CREATE)
def commercial_document_create(request):
    return commercial_document_form(
        request,
        initial={"document_date": date.today()},
        title="New Commercial Document",
        cancel_url="commercial_document_list",
    )


def commercial_document_form(
    request,
    initial=None,
    title="Commercial Document",
    cancel_url="commercial_document_list",
    cancel_kwargs=None,
):
    form = CommercialDocumentForm(
        request.POST or None, request.FILES or None, initial=initial
    )
    if request.method == "POST" and form.is_valid():
        document = form.save(commit=False)
        document.client = form.resolve_client()
        if document.client:
            document.client_name = document.client.name
            document.client_contact = document.client.contact_person
            document.client_email = document.client.email
            document.client_phone = document.client.phone
        else:
            document.client_name = form.cleaned_data.get("new_client_name", "").strip()
            document.client_contact = form.cleaned_data.get(
                "new_client_contact", ""
            ).strip()
            document.client_email = form.cleaned_data.get(
                "new_client_email", ""
            ).strip()
            document.client_phone = form.cleaned_data.get(
                "new_client_phone", ""
            ).strip()
        document.created_by = request.user
        document.save()
        messages.success(request, f"Document {document.document_number} saved.")
        return redirect("commercial_document_detail", pk=document.pk)
    return render(
        request,
        "operations/commercial_document_form.html",
        {
            "form": form,
            "title": title,
            "cancel_url": cancel_url,
            "cancel_kwargs": cancel_kwargs or {},
        },
    )


@access_required(UserModuleAccess.Module.COMMERCIAL_DOCUMENTS, ACTION_READ)
def commercial_document_detail(request, pk):
    document = get_object_or_404(
        CommercialDocument.objects.select_related(
            "client",
            "transport",
            "purchase_order",
            "requisition",
            "supplier",
            "created_by",
        ),
        pk=pk,
    )
    return render(
        request, "operations/commercial_document_detail.html", {"document": document}
    )


@access_required(UserModuleAccess.Module.COMMERCIAL_DOCUMENTS, ACTION_CREATE)
def business_client_create(request):
    form = BusinessClientForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        client = form.save()
        messages.success(request, f"Client {client.name} saved.")
        return redirect("commercial_document_list")
    return render(
        request,
        "operations/form_page.html",
        {
            "form": form,
            "title": "New Client",
            "action_label": "Save client",
            "cancel_url": "commercial_document_list",
        },
    )


@access_required(UserModuleAccess.Module.FINANCIAL_REPORTS, ACTION_READ)
def financial_report(request):
    query = request.GET.get("q", "").strip()
    record_type = request.GET.get("type", "all").strip() or "all"
    date_value = request.GET.get("date", "").strip()
    search_date = parse_date(date_value) if date_value else None
    records = FinancialRecord.objects.select_related(
        "client", "supplier", "document", "recorded_by"
    )
    if query:
        records = records.filter(
            Q(record_number__icontains=query)
            | Q(description__icontains=query)
            | Q(reference__icontains=query)
            | Q(client__name__icontains=query)
            | Q(supplier__name__icontains=query)
            | Q(document__document_number__icontains=query)
        ).distinct()
    allowed_types = {code for code, _label in FinancialRecord.RecordType.choices}
    if record_type in allowed_types:
        records = records.filter(record_type=record_type)
    if search_date:
        records = records.filter(record_date=search_date)
    totals = records.values("record_type").annotate(total=Sum("amount"))
    total_map = {row["record_type"]: row["total"] or Decimal("0") for row in totals}
    cash_in_total = total_map.get(FinancialRecord.RecordType.CASH_IN, Decimal("0"))
    expense_total = total_map.get(FinancialRecord.RecordType.CASH_OUT, Decimal("0"))
    loss_total = total_map.get(FinancialRecord.RecordType.LOSS, Decimal("0"))
    cash_out_total = expense_total + loss_total
    matching_count = records.count()
    records = records[:LIST_RESULTS_LIMIT]
    return render(
        request,
        "operations/financial_report.html",
        {
            "records": records,
            "query": query,
            "record_type": record_type,
            "record_types": FinancialRecord.RecordType.choices,
            "date_value": date_value,
            "matching_count": matching_count,
            "cash_in_total": cash_in_total,
            "cash_out_total": cash_out_total,
            "expense_total": expense_total,
            "loss_total": loss_total,
            "net_total": cash_in_total - cash_out_total,
        },
    )


@access_required(UserModuleAccess.Module.FINANCIAL_REPORTS, ACTION_CREATE)
def financial_record_create(request):
    form = FinancialRecordForm(
        request.POST or None, initial={"record_date": date.today()}
    )
    if request.method == "POST" and form.is_valid():
        record = form.save(commit=False)
        record.recorded_by = request.user
        record.save()
        messages.success(request, f"Financial record {record.record_number} saved.")
        return redirect("financial_report")
    return render(
        request,
        "operations/form_page.html",
        {
            "form": form,
            "title": "New financial record",
            "action_label": "Save record",
            "cancel_url": "financial_report",
        },
    )


@superuser_required
def user_access_list(request):
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "all").strip() or "all"
    users = (
        get_user_model().objects.prefetch_related("module_access").order_by("username")
    )
    if query:
        users = users.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
            | Q(module_access__module__icontains=query)
        ).distinct()
    if status == "active":
        users = users.filter(is_active=True)
    elif status == "inactive":
        users = users.filter(is_active=False)
    matching_count = users.count()
    users = users[:LIST_RESULTS_LIMIT]
    return render(
        request,
        "operations/user_access_list.html",
        {
            "managed_users": users,
            "query": query,
            "status": status,
            "matching_count": matching_count,
        },
    )


@superuser_required
def user_access_create(request):
    return user_access_form(request)


@superuser_required
def user_access_edit(request, user_id):
    user = get_object_or_404(
        get_user_model().objects.prefetch_related("module_access"), pk=user_id
    )
    return user_access_form(request, user)


def user_access_form(request, managed_user=None):
    is_create = managed_user is None
    if request.method == "POST":
        user_form = ManagedUserForm(
            request.POST, instance=managed_user, require_password=is_create
        )
        access_formset = ModuleAccessFormSet(request.POST, prefix="access")
        if user_form.is_valid() and access_formset.is_valid():
            saved_user = user_form.save()
            save_access_rows(saved_user, access_formset)
            messages.success(request, f"Access updated for {saved_user.username}.")
            return redirect("user_access_list")
    else:
        user_form = ManagedUserForm(instance=managed_user, require_password=is_create)
        access_formset = ModuleAccessFormSet(
            initial=access_initial(managed_user), prefix="access"
        )

    return render(
        request,
        "operations/user_access_form.html",
        {
            "managed_user": managed_user,
            "user_form": user_form,
            "access_formset": access_formset,
            "access_rows": access_rows(access_formset),
            "title": "Create User" if is_create else f"Edit {managed_user.username}",
        },
    )


@superuser_required
def application_setup(request):
    setting = ApplicationSetting.load()
    form = ApplicationSettingForm(
        request.POST or None, request.FILES or None, instance=setting
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Application setup updated.")
        return redirect("application_setup")
    return render(
        request,
        "operations/application_setup.html",
        {"form": form, "title": "Application Setup"},
    )
