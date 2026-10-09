import io
import pandas as pd

# EPF Constants
EPF_WAGE_CEILING = 15000.0
EPF_EMP_RATE = 0.12
EPS_EMPLOYER_RATE = 0.0833
MAX_EPS_WAGES = 15000.0
MAX_EPS_CONTRIB = 1250.0

# ESI Constants
ESI_GROSS_CEILING = 21000.0
ESI_EMP_RATE = 0.0075
ESI_EMPLOYER_RATE = 0.0325

def calculate_epf(basic_pay: float, enforce_ceiling: bool = True) -> dict:
    epf_wages = min(basic_pay, EPF_WAGE_CEILING) if enforce_ceiling else basic_pay
    epf_emp = round(epf_wages * EPF_EMP_RATE)
    
    eps_wages = min(basic_pay, MAX_EPS_WAGES)
    eps_employer = round(min(eps_wages * EPS_EMPLOYER_RATE, MAX_EPS_CONTRIB))
    epf_employer = epf_emp - eps_employer
    
    return {
        "epf_wages": epf_wages,
        "eps_wages": eps_wages,
        "epf_emp": epf_emp,
        "eps_employer": eps_employer,
        "epf_employer": max(0, epf_employer),
        "total_epf_employer": epf_emp
    }

def calculate_esi(gross_salary: float) -> dict:
    if gross_salary > ESI_GROSS_CEILING:
        return {"esi_applicable": False, "esi_emp": 0.0, "esi_employer": 0.0}
    
    esi_emp = round(gross_salary * ESI_EMP_RATE)
    esi_employer = round(gross_salary * ESI_EMPLOYER_RATE)
    return {
        "esi_applicable": True,
        "esi_emp": esi_emp,
        "esi_employer": esi_employer
    }

def calculate_professional_tax(gross_salary: float, state: str = "Maharashtra", month: str = "01") -> float:
    state_lower = state.lower() if state else "maharashtra"
    if state_lower == "maharashtra":
        if gross_salary <= 7500:
            return 0.0
        elif gross_salary <= 10000:
            return 175.0
        else:
            return 250.0 if month == "02" else 200.0
    elif state_lower == "karnataka":
        if gross_salary < 25000:
            return 0.0
        else:
            return 200.0
    elif state_lower == "west bengal":
        if gross_salary <= 10000:
            return 0.0
        elif gross_salary <= 15000:
            return 110.0
        elif gross_salary <= 25000:
            return 130.0
        elif gross_salary <= 40000:
            return 150.0
        else:
            return 200.0
    elif state_lower == "tamil nadu":
        if gross_salary <= 21000:
            return 0.0
        elif gross_salary <= 30000:
            return 100.0
        elif gross_salary <= 45000:
            return 235.0
        elif gross_salary <= 60000:
            return 510.0
        else:
            return 760.0
    elif state_lower == "gujarat":
        if gross_salary <= 5999:
            return 0.0
        elif gross_salary <= 8999:
            return 80.0
        elif gross_salary <= 11999:
            return 150.0
        else:
            return 200.0
    else:
        return 200.0 if gross_salary > 15000 else 0.0

def calculate_tds_estimate(gross_annual: float, regime: str = "new") -> float:
    std_deduction = 75000.0 if regime == "new" else 50000.0
    taxable = max(0.0, gross_annual - std_deduction)
    
    tax = 0.0
    if regime == "new":
        if taxable <= 300000:
            tax = 0.0
        elif taxable <= 700000:
            tax = (taxable - 300000) * 0.05
        elif taxable <= 1000000:
            tax = 20000 + (taxable - 700000) * 0.10
        elif taxable <= 1200000:
            tax = 50000 + (taxable - 1000000) * 0.15
        elif taxable <= 1500000:
            tax = 80000 + (taxable - 1200000) * 0.20
        else:
            tax = 140000 + (taxable - 1500000) * 0.30
        
        if taxable <= 700000:
            tax = 0.0
    else:
        if taxable <= 250000:
            tax = 0.0
        elif taxable <= 500000:
            tax = (taxable - 250000) * 0.05
        elif taxable <= 1000000:
            tax = 12500 + (taxable - 500000) * 0.20
        else:
            tax = 112500 + (taxable - 1000000) * 0.30
    
    tax_with_cess = tax * 1.04
    monthly_tds = round(tax_with_cess / 12.0)
    return monthly_tds

def calculate_gratuity(basic_pay: float, years_of_service: float) -> dict:
    """Payment of Gratuity Act 1972 formula: (15 / 26) * Basic Pay * Years of Service"""
    if years_of_service < 5.0:
        return {"eligible": False, "amount": 0.0, "reason": "Minimum 5 continuous years required"}
    gratuity = round((15.0 / 26.0) * basic_pay * years_of_service)
    return {"eligible": True, "amount": min(2000000.0, gratuity), "reason": "Eligible under Gratuity Act"}

def calculate_bonus(basic_pay: float, percentage: float = 8.33) -> float:
    """Payment of Bonus Act formula: Min 8.33%, Max 20% on Basic or ₹7000 ceiling"""
    wages = min(basic_pay, 7000.0)
    bonus_annual = (wages * (percentage / 100.0)) * 12.0
    return round(bonus_annual)

def generate_epf_ecr_file(payroll_records: list) -> str:
    lines = []
    for rec in payroll_records:
        uan = rec.get("uan_no") or "100000000000"
        name = rec.get("emp_name") or "EMPLOYEE"
        gross = int(rec.get("gross_salary", 0))
        epf_wages = int(min(rec.get("basic_paid", 0), EPF_WAGE_CEILING))
        eps_wages = epf_wages
        edli_wages = epf_wages
        ee_share = int(rec.get("epf_emp", 0))
        eps_share = int(rec.get("eps_employer", 0))
        er_share = int(rec.get("epf_employer", 0))
        ncp_days = int(rec.get("loss_of_pay_days", 0))
        refund = 0

        line = f"{uan}#~#{name}#~#{gross}#~#{epf_wages}#~#{eps_wages}#~#{edli_wages}#~#{ee_share}#~#{eps_share}#~#{er_share}#~#{ncp_days}#~#{refund}"
        lines.append(line)
    
    return "\n".join(lines)

def generate_esi_challan_csv(payroll_records: list) -> str:
    """Official ESIC Monthly Return CSV Upload Format"""
    rows = []
    for rec in payroll_records:
        rows.append({
            "IP Number": rec.get("esi_no") or "3100000000",
            "IP Name": rec.get("emp_name", ""),
            "No of Days Wages Paid": 30 - int(rec.get("loss_of_pay_days", 0)),
            "Total Monthly Wages": rec.get("gross_salary", 0.0),
            "Reason Code for 0 Wages": "",
            "Last Working Day": ""
        })
    df = pd.DataFrame(rows)
    return df.to_csv(index=False)

def generate_bank_disbursement_csv(payroll_records: list, bank_format: str = "HDFC") -> str:
    rows = []
    for rec in payroll_records:
        rows.append({
            "Beneficiary Account No": rec.get("bank_acc", ""),
            "Beneficiary Name": rec.get("emp_name", ""),
            "IFSC Code": rec.get("ifsc_code", ""),
            "Net Salary Amount": rec.get("net_salary", 0.0),
            "Payment Date": rec.get("processed_at", "")[:10],
            "Narration": f"SALARY {rec.get('month_year', '')}"
        })
    df = pd.DataFrame(rows)
    return df.to_csv(index=False)
