import streamlit as st
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta
import os

# Set page config
st.set_page_config(
    page_title="Pension Calculator",
    page_icon="💰",
    layout="wide"
)

# Constants
MANAGEMENT_CHARGES = 0.065
REGULATORY_CHARGES = 0.01
INTEREST_RATE = 0.105
DISCOUNT_RATE = 0.08
MIN_LUMPSUM = 0
MIN_REG_LUMPSUM = 0.25
FINAL_SALARY_PERCENT = 1
MIN_PENSION_PAYOUT = 0.5
INTEREST_RATE_NET_CHARGES = INTEREST_RATE * (1 - MANAGEMENT_CHARGES - REGULATORY_CHARGES)

# Helper functions
def datedif(start_date, end_date, unit):
    delta = relativedelta(end_date, start_date)
    
    if unit == "Y":
        return delta.years
    elif unit == "M":
        return delta.years * 12 + delta.months
    elif unit == "D":
        return (end_date - start_date).days
    elif unit == "YM":
        return delta.months
    elif unit == "MD":
        return delta.days
    elif unit == "YD":
        delta_this_year = datetime(end_date.year, end_date.month, end_date.day) - datetime(end_date.year, start_date.month, start_date.day)
        return delta_this_year.days if delta_this_year.days >= 0 else (datetime(end_date.year + 1, start_date.month, start_date.day) - datetime(end_date.year, end_date.month, end_date.day)).days
    else:
        raise ValueError("Invalid unit. Use 'Y', 'M', 'D', 'YM', 'MD', or 'YD'.")

def yearfrac(start_date, end_date):
    delta = relativedelta(end_date, start_date)
    return delta.years + delta.months / 12 + delta.days / 365.25

def pmt(rate, nper, pv, fv=0, when=0):
    if rate == 0:
        return -(pv + fv) / nper
    else:
        factor = (1 + rate) ** nper
        return -(pv * factor + fv) / ((1 + rate * when) * (factor - 1) / rate)

def pv(rate, nper, pmt, fv=0, when=0):
    if rate == 0:
        return -pmt * nper - fv
    else:
        factor = (1 + rate) ** nper
        return -(pmt * (1 + rate * when) * (factor - 1) / rate + fv) / factor

def get_annual_salary(salary_structure, grade_level, step, df):
    result = df[
        (df["Salary Structure"].str.lower() == salary_structure.lower()) &
        (df["Grade Level"] == str(grade_level)) &
        (df["Step"] == str(step))
    ]
    
    if not result.empty:
        return result.iloc[0]["Annual Salary"]
    else:
        return None

def lookup_ax(gender, frequency, retirement_age, male4, male12, female4, female12):
    # Select the correct table based on gender and frequency
    if gender == "M" and frequency == 4:
        table = male4
    elif gender == "M" and frequency == 12:
        table = male12
    elif gender == "F" and frequency == 4:
        table = female4
    elif gender == "F" and frequency == 12:
        table = female12
    else:
        raise ValueError("Invalid combination of gender and frequency.")
    
    # Perform the lookup
    match = table.loc[table['age'] == retirement_age]
    
    if not match.empty:
        ax_value = match.iloc[0]['ax']
        return ax_value
    else:
        raise ValueError(f"Age {retirement_age} not found in selected table.")

def determine_lumpsum(max_lumpsum, adjusted_rsa, regulatory):
    if max_lumpsum > adjusted_rsa:
        return adjusted_rsa
    elif max_lumpsum > regulatory:
        return max_lumpsum
    else:
        return regulatory

def compute_final_monthly_pension(final_lumpsum, min_lumpsum, max_lumpsum, regulatory_lumpsum, new_adjusted_balance, monthly_rate, nper):
    # 1. Minimum Lumpsum Check
    if final_lumpsum < min_lumpsum:
        raise ValueError("❌ Error: Lumpsum is less than the minimum allowed.")

    # 2. Max > Reg & Lumpsum > Max → Error
    if max_lumpsum > regulatory_lumpsum and final_lumpsum > max_lumpsum:
        raise ValueError("❌ Error: Lumpsum exceeds the Maximum Lumpsum limit.")

    # 3. Max < Reg & Lumpsum > Reg → Error
    if max_lumpsum < regulatory_lumpsum and final_lumpsum > regulatory_lumpsum:
        raise ValueError("❌ Error: Lumpsum exceeds the Regulatory Lumpsum limit.")

    # 4. All good: compute final pension from residual RSA
    residual = new_adjusted_balance - final_lumpsum
    pension = -1 * pmt(monthly_rate, nper, residual, fv=0, when=1)
    return pension

def get_final_arrears_months(negotiated_months, max_allowable_months):
    if negotiated_months > max_allowable_months:
        raise ValueError("❌ Error: Negotiated months exceed the maximum allowable arrears.")
    elif negotiated_months < max_allowable_months:
        return negotiated_months
    else:
        return max_allowable_months

def calculate_pension_arrears(frequency, final_arrears_months, final_monthly_pension):
    if frequency == 4:
        # Quarterly frequency: convert months to quarters (i.e., divide by 3)
        arrears = (final_arrears_months / 3) * final_monthly_pension
    else:
        # Monthly frequency
        arrears = final_arrears_months * final_monthly_pension
    return arrears

# Load CSV files function - PRELOADED AT STARTUP
@st.cache_data
def load_csv_files():
    """Load all required CSV files at startup"""
    files = {}
    required_files = {
        'Male12': 'Male12.csv',
        'Female12': 'Female12.csv', 
        'Male4': 'Male4.csv',
        'Female4': 'Female4.csv',
        'SalaryStructure': 'SalaryStructure.csv'
    }
    
    missing_files = []
    for key, filename in required_files.items():
        if os.path.exists(filename):
            try:
                df = pd.read_csv(filename)
                if key == 'SalaryStructure':
                    df['Annual Salary'] = df['Annual Salary'].astype(float)
                files[key] = df
            except Exception as e:
                missing_files.append(f"{filename} (Error: {str(e)})")
        else:
            missing_files.append(filename)
    
    if missing_files:
        return None, missing_files
    
    return files, []

# Load CSV files at startup
csv_data, missing_files = load_csv_files()

# Main Streamlit app
def main():
    st.title("💰 Pension Calculator")
    st.markdown("---")
    
    # Check if CSV files are loaded
    if csv_data is None:
        st.error("❌ Required CSV files are missing or have errors:")
        for file in missing_files:
            st.error(f"• {file}")
        st.info("Please ensure the following CSV files are in the same directory as this app:")
        st.info("• Male12.csv\n• Female12.csv\n• Male4.csv\n• Female4.csv\n• SalaryStructure.csv")
        return
    
    # Display successful file loading
    st.success("✅ All required CSV files loaded successfully!")
    
    # Extract dataframes from preloaded data
    male12 = csv_data['Male12']
    female12 = csv_data['Female12']
    male4 = csv_data['Male4']
    female4 = csv_data['Female4']
    salarystructure = csv_data['SalaryStructure']
    
    st.markdown("---")
    
    # User input section
    st.header("👤 Client Information")
    
    col1, col2 = st.columns(2)
    
    with col1:
        gender = st.selectbox("Gender", ["M", "F"], format_func=lambda x: "Male" if x == "M" else "Female")
        sector = st.selectbox("Sector", ["PU", "PR"], format_func=lambda x: "Public" if x == "PU" else "Private")
        dob = st.date_input("Date of Birth", min_value=datetime(1940, 1, 1).date())
        retirement_date = st.date_input("Retirement Date", min_value=datetime(1940, 1, 1).date())
    
    with col2:
        programming_date = st.date_input("Date of Programming", value=datetime.now().date(), min_value=datetime(1940, 1, 1).date())
        rsa_balance = st.number_input("RSA Balance", min_value=0.0, format="%.2f")
        frequency = st.selectbox("Frequency", [4, 12], format_func=lambda x: "Quarterly" if x == 4 else "Monthly")
    
    # Salary determination
    st.header("💰 Salary Information")
    
    cutoff_date = datetime.strptime("01-09-2024", "%d-%m-%Y").date()
    
    if sector == 'PU' and retirement_date >= cutoff_date:
        st.subheader("Salary Structure Details")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            salary_structure = st.text_input("Salary Structure (e.g., CONPOSS)")
        with col2:
            grade_level = st.text_input("Grade Level")
        with col3:
            step = st.text_input("Step")
        
        if salary_structure and grade_level and step:
            validated_salary = get_annual_salary(salary_structure, grade_level, step, salarystructure)
            if validated_salary is not None:
                st.success(f"Annual Salary: ₦{validated_salary:,.2f}")
            else:
                st.error("No matching salary structure found")
                validated_salary = None
        else:
            validated_salary = None
    else:
        monthly_salary = st.number_input("Monthly Salary", min_value=0.0, format="%.2f")
        validated_salary = monthly_salary * 12 if monthly_salary > 0 else None
    
    # Initial calculation button to show parameters
    if st.button("Get Calculation Parameters", type="primary"):
        if validated_salary is None:
            st.error("Please provide valid salary information")
            return
        
        if rsa_balance <= 0:
            st.error("Please provide a valid RSA balance")
            return
        
        try:
            # Convert dates to datetime objects
            dob_dt = datetime.combine(dob, datetime.min.time())
            retirement_dt = datetime.combine(retirement_date, datetime.min.time())
            programming_dt = datetime.combine(programming_date, datetime.min.time())
            
            # Compute ages
            current_age = datedif(dob_dt, programming_dt, "Y")
            retirement_age = datedif(dob_dt, retirement_dt, "Y")
            
            # Calculate max arrears
            max_arrears_years = yearfrac(retirement_dt, programming_dt)
            max_arrears_months = max_arrears_years * 12
            
            # Cap maxArrears at 6 months for PR sector
            if sector == "PR":
                max_arrears_months = min(max_arrears_months, 6)
            
            max_arrears = round(max_arrears_months, 0)
            
            # Store values in session state for later use
            st.session_state.current_age = current_age
            st.session_state.retirement_age = retirement_age
            st.session_state.max_arrears = max_arrears
            st.session_state.validated_salary = validated_salary
            st.session_state.rsa_balance = rsa_balance
            st.session_state.dob_dt = dob_dt
            st.session_state.retirement_dt = retirement_dt
            st.session_state.programming_dt = programming_dt
            st.session_state.gender = gender
            st.session_state.frequency = frequency
            st.session_state.sector = sector
            
            # Display calculation parameters
            st.markdown("---")
            st.header("📊 Calculation Parameters")
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Current Age", f"{current_age} years")
                st.metric("Retirement Age", f"{retirement_age} years")
            with col2:
                st.metric("Max Arrears", f"{int(max_arrears)} months")
                st.metric("Annual Salary", f"₦{validated_salary:,.2f}")
            with col3:
                st.metric("RSA Balance", f"₦{rsa_balance:,.2f}")
            
        except Exception as e:
            st.error(f"Error in calculation: {str(e)}")
    
    # Show pension configuration inputs if parameters are available
    if hasattr(st.session_state, 'max_arrears'):
        st.markdown("---")
        st.header("⚙️ Pension Configuration")
        
        col1, col2 = st.columns(2)
        
        with col1:
            preferred_arrears = st.number_input(
                f"Preferred Arrears (max {int(st.session_state.max_arrears)} months)",
                min_value=0,
                max_value=int(st.session_state.max_arrears),
                value=0,
                step=1,
                key="preferred_arrears"
            )
        
        # Calculate adjusted balance and lumpsum limits based on preferred arrears
        preferred_max_arrears_years = preferred_arrears / 12
        new_adjusted_balance = st.session_state.rsa_balance * ((1 + DISCOUNT_RATE) ** -preferred_max_arrears_years)
        
        # Calculate lumpsum limits
        monthly_rate = INTEREST_RATE_NET_CHARGES / 12
        ax_value = lookup_ax(st.session_state.gender, st.session_state.frequency, st.session_state.retirement_age, male4, male12, female4, female12)
        nc = ax_value - (11/24)
        nper = 2 * st.session_state.frequency * nc
        
        fifty_percent_salary = (st.session_state.validated_salary / st.session_state.frequency) * MIN_PENSION_PAYOUT
        regulatory_lumpsum = st.session_state.rsa_balance * 0.25
        max_lumpsum = max(0, (new_adjusted_balance + pv(monthly_rate, nper, fifty_percent_salary, fv=0, when=1)))
        recommended_lumpsum = determine_lumpsum(max_lumpsum, new_adjusted_balance, regulatory_lumpsum)
        
        with col2:
            negotiated_lumpsum = st.number_input(
                f"Negotiated Lumpsum (max ₦{recommended_lumpsum:,.2f})",
                min_value=0.0,
                max_value=float(recommended_lumpsum),
                value=0.0,
                format="%.2f",
                step=1000.0,
                key="negotiated_lumpsum"
            )
        
        # Final calculation button
        if st.button("Calculate Final Pension", type="secondary"):
            try:
                # Final calculations
                final_lumpsum = negotiated_lumpsum
                final_monthly_pension = compute_final_monthly_pension(
                    final_lumpsum, MIN_LUMPSUM, max_lumpsum, regulatory_lumpsum, 
                    new_adjusted_balance, monthly_rate, nper
                )
                
                final_arrears_months = get_final_arrears_months(preferred_arrears, st.session_state.max_arrears)
                pension_arrears = calculate_pension_arrears(st.session_state.frequency, final_arrears_months, final_monthly_pension)
                
                # Display results
                st.markdown("---")
                st.header("✅ Calculation Results")
                
                col1, col2 = st.columns(2)
                
                with col1:
                    st.metric("Final Monthly Pension", f"₦{final_monthly_pension:,.2f}")
                    st.metric("Final Approved Lumpsum", f"₦{final_lumpsum:,.2f}")
                    st.metric("Final Arrears Months", f"{int(final_arrears_months)} months")
                
                with col2:
                    st.metric("Pension Arrears Amount", f"₦{pension_arrears:,.2f}")
                    st.metric("Total Benefit Payable", f"₦{final_lumpsum + pension_arrears:,.2f}")
                    st.metric("Annuity Premium", f"₦{st.session_state.rsa_balance - final_lumpsum - pension_arrears - final_monthly_pension:,.2f}")
                
                # Summary table
                st.markdown("---")
                st.header("📋 Summary")
                
                summary_data = {
                    "Item": [
                        "Final Monthly Pension",
                        "Final Approved Lumpsum", 
                        "Final Arrears Months",
                        "Pension Arrears Amount",
                        "Total Benefit Payable",
                        "Annuity Premium"
                    ],
                    "Value": [
                        f"₦{final_monthly_pension:,.2f}",
                        f"₦{final_lumpsum:,.2f}",
                        f"{int(final_arrears_months)} months",
                        f"₦{pension_arrears:,.2f}",
                        f"₦{final_lumpsum + pension_arrears:,.2f}",
                        f"₦{st.session_state.rsa_balance - final_lumpsum - pension_arrears - final_monthly_pension:,.2f}"
                    ]
                }
                
                summary_df = pd.DataFrame(summary_data)
                st.table(summary_df)
                
            except Exception as e:
                st.error(f"Error in final calculation: {str(e)}")

if __name__ == "__main__":
    main()
