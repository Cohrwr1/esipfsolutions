import io
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

def generate_pdf_payslip(company: dict, employee: dict, payroll: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36
    )

    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        textColor=colors.HexColor('#1E3A8A'),
        alignment=1 # Center
    )

    subtitle_style = ParagraphStyle(
        'SubTitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#475569'),
        alignment=1
    )

    bold_label = ParagraphStyle(
        'BoldLabel',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#0F172A')
    )

    val_style = ParagraphStyle(
        'ValStyle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#334155')
    )

    story = []

    # 1. Company Header
    story.append(Paragraph(company.get("company_name", "COMPANY NAME"), title_style))
    comp_addr = f"{company.get('address', '')} | EPF Code: {company.get('epf_code', 'N/A')} | ESI Code: {company.get('esi_code', 'N/A')}"
    story.append(Paragraph(comp_addr, subtitle_style))
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#1E3A8A'), spaceAfter=15))

    # 2. Pay Slip Title & Month
    payslip_title = ParagraphStyle(
        'PTitle',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=14,
        alignment=1,
        textColor=colors.HexColor('#0F172A')
    )
    story.append(Paragraph(f"SALARY SLIP FOR THE MONTH OF {payroll.get('month_year', '')}", payslip_title))
    story.append(Spacer(1, 15))

    # 3. Employee Info Block Table
    emp_info_data = [
        [
            Paragraph("<b>Employee Code:</b>", bold_label), Paragraph(str(employee.get("emp_code", "")), val_style),
            Paragraph("<b>Employee Name:</b>", bold_label), Paragraph(str(employee.get("name", "")), val_style)
        ],
        [
            Paragraph("<b>Designation:</b>", bold_label), Paragraph(str(employee.get("designation", "")), val_style),
            Paragraph("<b>Department:</b>", bold_label), Paragraph(str(employee.get("department", "")), val_style)
        ],
        [
            Paragraph("<b>Date of Joining:</b>", bold_label), Paragraph(str(employee.get("doj", "")), val_style),
            Paragraph("<b>Bank Account:</b>", bold_label), Paragraph(str(employee.get("bank_acc", "")), val_style)
        ],
        [
            Paragraph("<b>UAN Number:</b>", bold_label), Paragraph(str(employee.get("uan_no", "N/A")), val_style),
            Paragraph("<b>PF / ESI No:</b>", bold_label), Paragraph(str(employee.get("esi_no", "N/A")), val_style)
        ]
    ]

    emp_table = Table(emp_info_data, colWidths=[110, 160, 110, 160])
    emp_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#E2E8F0')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(emp_table)
    story.append(Spacer(1, 15))

    # 4. Earnings & Deductions Comparison Table
    earn_ded_data = [
        [
            Paragraph("<b>EARNINGS</b>", bold_label), Paragraph("<b>AMOUNT (₹)</b>", bold_label),
            Paragraph("<b>DEDUCTIONS</b>", bold_label), Paragraph("<b>AMOUNT (₹)</b>", bold_label)
        ],
        [
            Paragraph("Basic Salary", val_style), Paragraph(f"{payroll.get('basic_paid', 0.0):,.2f}", val_style),
            Paragraph("Employee EPF (12%)", val_style), Paragraph(f"{payroll.get('epf_emp', 0.0):,.2f}", val_style)
        ],
        [
            Paragraph("House Rent Allowance (HRA)", val_style), Paragraph(f"{payroll.get('hra_paid', 0.0):,.2f}", val_style),
            Paragraph("Employee ESI (0.75%)", val_style), Paragraph(f"{payroll.get('esi_emp', 0.0):,.2f}", val_style)
        ],
        [
            Paragraph("Special Allowances", val_style), Paragraph(f"{payroll.get('allowances_paid', 0.0):,.2f}", val_style),
            Paragraph("Professional Tax (PT)", val_style), Paragraph(f"{payroll.get('pt_deduction', 0.0):,.2f}", val_style)
        ],
        [
            Paragraph("Overtime Pay", val_style), Paragraph(f"{payroll.get('overtime_pay', 0.0):,.2f}", val_style),
            Paragraph("TDS / Income Tax", val_style), Paragraph(f"{payroll.get('tds_deduction', 0.0):,.2f}", val_style)
        ],
        [
            Paragraph("", val_style), Paragraph("", val_style),
            Paragraph("Loan EMI / Advance", val_style), Paragraph(f"{payroll.get('loan_emi', 0.0):,.2f}", val_style)
        ],
        [
            Paragraph("", val_style), Paragraph("", val_style),
            Paragraph("Loss of Pay (LOP)", val_style), Paragraph(f"{payroll.get('lop_deduction', 0.0):,.2f}", val_style)
        ],
        [
            Paragraph("<b>GROSS EARNINGS</b>", bold_label), Paragraph(f"<b>₹{payroll.get('gross_salary', 0.0):,.2f}</b>", bold_label),
            Paragraph("<b>TOTAL DEDUCTIONS</b>", bold_label), Paragraph(f"<b>₹{payroll.get('total_deductions', 0.0):,.2f}</b>", bold_label)
        ]
    ]

    table = Table(earn_ded_data, colWidths=[160, 110, 160, 110])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E0F2FE')),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#F1F5F9')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#CBD5E1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('ALIGN', (3, 0), (3, -1), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(table)
    story.append(Spacer(1, 15))

    # 5. Net Salary Summary Block
    net_val = payroll.get('net_salary', 0.0)
    net_box_data = [
        [
            Paragraph(f"<font size=12 color='#0F172A'><b>NET SALARY PAYABLE:</b></font>", styles['Normal']),
            Paragraph(f"<font size=14 color='#166534'><b>₹{net_val:,.2f}</b></font>", styles['Normal'])
        ]
    ]
    net_table = Table(net_box_data, colWidths=[300, 240])
    net_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#DCFCE7')),
        ('BOX', (0, 0), (-1, -1), 1.5, colors.HexColor('#22C55E')),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(net_table)
    story.append(Spacer(1, 20))

    # 6. Verification Footer
    footer_text = "This is a computer-generated salary slip generated via ESIPFSolutions Cloud Enterprise. No signature required."
    story.append(Paragraph(f"<font color='#64748B' size=8><i>{footer_text}</i></font>", subtitle_style))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
