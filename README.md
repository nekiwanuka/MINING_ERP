# Mining ERP

Django and Django REST Framework ERP slice for requisitions, procurement, supplier invoices, purchase receipts, and transportation cost management.

## Setup

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_demo
.\.venv\Scripts\python.exe manage.py runserver
```

Demo users use the password `MiningERP2026!`:

- `requester` submits requisitions.
- `procurement` accepts requisitions, creates purchase inquiries, loads supplier invoices, creates purchase orders, and uploads receipts.
- `transport` creates transport records, uploads transport attachments, adds custom government charges, and views transport reports.
- `admin` can access Django admin.

Protected APIs are available under `/api/` and require authentication. Browser API login is available under `/api-auth/login/`.

## Render Test Deployment

This project includes `build.sh` and `render.yaml` for Render.

1. Push the latest code to GitHub.
2. Open Render, choose **New + > Web Service**, and connect `nekiwanuka/MINING_ERP`.
3. Use these settings if you create it manually:
	- Build command: `bash build.sh`
	- Start command: `bash start.sh`
	- Environment: Python
4. Add environment variables:
	- `DEBUG=false`
	- `SECRET_KEY=` generate a secure random value in Render
	- `ALLOWED_HOSTS=.onrender.com,localhost,127.0.0.1`
	- `CSRF_TRUSTED_ORIGINS=https://YOUR-RENDER-SERVICE.onrender.com`
	- `ADMIN_USERNAME=admin`
	- `ADMIN_EMAIL=your-email@example.com`
	- `ADMIN_PASSWORD=` enter a secure password you will use to log in
5. On deploy, `start.sh` runs migrations and creates/updates the admin user from those `ADMIN_*` variables. Use those credentials on the login page.

If you have Render Shell access, you can also create an admin manually:

```bash
python manage.py createsuperuser
```

For quick demo data, you can also run:

```bash
python manage.py seed_demo
```

Note: the current test deployment uses SQLite. On Render free/test services, SQLite data can reset when the instance is rebuilt or restarted. Use Render PostgreSQL later for persistent production data.

## Procurement Review and Supplier PO Workflow

Use **Procurement > Workflow manual** in the app for operator instructions.

1. Requester submits a requisition.
2. Procurement opens **Review / edit**, confirms or adjusts item descriptions and pieces, then saves the review to accept the requisition.
3. Procurement creates supplier purchase orders from each reviewed item.
4. Items can be split across different suppliers by item type or by partial quantity.
5. Each PO records the supplier, ordered quantity, amount, order date, delivery method, and supplier message. Procurement can select an existing supplier or type a new supplier name, contact, email, and phone directly on the PO form.
6. Open the PO detail page to send by email, send by WhatsApp, or print a hard copy.
7. The requisition becomes purchased only when all item quantities have been fully ordered.

## Shared Vehicle Billing Workflow

Use **Transport > Billing manual** in the app for the operator workflow.

1. Create one transport record per transit. The system generates one unique transit number.
2. Add one cargo row for each customer sharing the vehicle.
3. Record each customer's loading point, offloading point, loading sequence, offloading sequence, billable distance, cargo units, and direct customer charges.
4. Add each border, toll, duty, permit, tax, customs, or checkpoint fee as its own transit/government fee row.
5. Set the fee route sequence so the system knows which customers were still onboard when that fee happened.
6. Open the transport detail page and click **Generate invoices**.
7. Review one generated draft invoice per customer. Direct charges stay with the customer, shared fleet charges are split by chargeable units and distance, and transit/government fees are split only among customers onboard at that fee point.
