import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
from dateutil.relativedelta import relativedelta
import warnings
import io
import os
warnings.filterwarnings('ignore')

class PensionCalculator:
    def __init__(self):
        # Constants
        self.management_charges = 0.065
        self.regulatory_charges = 0.01
        self.interest_rate = 0.105
        self.discount_rate = 0.08
        self.min_lumpsum = 0
        self.min_reg_lumpsum = 0.25
        self.final_salary_percent = 1
        self.min_pension_payout = 0.5
        self.interest_rate_net_charges = self.interest_rate * (1 - self.management_charges - self.regulatory_charges)
        self.monthly_rate = self.interest_rate_net_charges / 12
        self.cutoff_date = datetime.strptime("01-09-2024", "%d-%m-%Y")
        
        # Load lookup tables
        self.load_lookup_tables()
    
    def load_lookup_tables(self):
        """Load all required CSV files"""
        try:
            # Load CSV files from current directory
            self.male12 = pd.read_csv("Male12.csv")
            self.female12 = pd.read_csv("Female12.csv")
            self.male4 = pd.read_csv("Male4.csv")
            self.female4 = pd.read_csv("Female4.csv")
            self.salary_structure = pd.read_csv("SalaryStructure.csv")
            self.salary_structure['Annual Salary'] = self.salary_structure['Annual Salary'].astype(float)
            return True
        except Exception as e:
            st.error(f"❌ Error loading lookup tables: {e}")
            return False
    
    def datedif(self, start_date, end_date, unit):
        """Calculate date differences similar to Excel DATEDIF"""
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
    
    def yearfrac(self, start_date, end_date):
        """Calculate year fraction using actual/actual method"""
        delta = relativedelta(end_date, start_date)
        return delta.years + delta.months / 12 + delta.days / 365.25
    
    def get_annual_salary(self, salary_structure, grade_level, step):
        """Get annual salary from salary structure table"""
        result = self.salary_structure[
            (self.salary_structure["Salary Structure"].str.lower() == str(salary_structure).lower()) &
            (self.salary_structure["Grade Level"] == str(grade_level)) &
            (self.salary_structure["Step"] == str(step))
        ]
        
        if not result.empty:
            return result.iloc[0]["Annual Salary"]
        else:
            return None
    
    def lookup_ax(self, gender, frequency, retirement_age):
        """Lookup ax value from appropriate table"""
        if gender.upper() == "M" and frequency == 4:
            table = self.male4
        elif gender.upper() == "M" and frequency == 12:
            table = self.male12
        elif gender.upper() == "F" and frequency == 4:
            table = self.female4
        elif gender.upper() == "F" and frequency == 12:
            table = self.female12
        else:
            raise ValueError(f"Invalid combination of gender ({gender}) and frequency ({frequency}).")
        
        match = table.loc[table['age'] == retirement_age]
        
        if not match.empty:
            return match.iloc[0]['ax']
        else:
            raise ValueError(f"Age {retirement_age} not found in selected table.")
    
    def pmt(self, rate, nper, pv, fv=0, when=0):
        """Calculate payment amount (similar to Excel PMT function)"""
        if rate == 0:
            return -(pv + fv) / nper
        else:
            factor = (1 + rate) ** nper
            return -(pv * factor + fv) / ((1 + rate * when) * (factor - 1) / rate)
    
    def pv(self, rate, nper, pmt, fv=0, when=0):
        """Calculate present value (similar to Excel PV function)"""
        if rate == 0:
            return -pmt * nper - fv
        else:
            factor = (1 + rate) ** nper
            return -(pmt * (1 + rate * when) * (factor - 1) / rate + fv) / factor
    
    def determine_lumpsum(self, max_lumpsum, adjusted_rsa, regulatory):
        """Determine recommended lumpsum"""
        if max_lumpsum > adjusted_rsa:
            return adjusted_rsa
        elif max_lumpsum > regulatory:
            return max_lumpsum
        else:
            return regulatory
    
    def calculate_pension_arrears(self, frequency, final_arrears_months, final_monthly_pension):
        """Calculate pension arrears amount"""
        if frequency == 4:
            arrears = (final_arrears_months / 3) * final_monthly_pension
        else:
            arrears = final_arrears_months * final_monthly_pension
        return arrears
    
    def process_single_client(self, row):
        """Process a single client's pension calculation"""
        try:
            # Parse dates
            dob = pd.to_datetime(row['date_of_birth'], format='%d-%m-%Y')
            retirement_date = pd.to_datetime(row['retirement_date'], format='%d-%m-%Y')
            programming_date = pd.to_datetime(row['programming_date'], format='%d-%m-%Y')
            
            # Extract other parameters
            gender = str(row['gender']).upper()
            sector = str(row['sector']).upper()
            frequency = int(row['frequency'])
            rsa_balance = float(row['rsa_balance'])
            
            # Calculate ages
            current_age = self.datedif(dob, programming_date, "Y")
            retirement_age = self.datedif(dob, retirement_date, "Y")
            
            # Determine validated salary
            if sector == 'PU' and retirement_date >= self.cutoff_date:
                # Use salary structure
                salary_structure = row['salary_structure']
                grade_level = row['grade_level']
                step = row['step']
                validated_salary = self.get_annual_salary(salary_structure, grade_level, step)
                if validated_salary is None:
                    return self.create_error_result(row, "Salary structure not found")
            else:
                # Use monthly salary
                monthly_salary = float(row['monthly_salary'])
                validated_salary = monthly_salary * 12
            
            # Calculate max arrears (automatically use maximum available)
            max_arrears_years = self.yearfrac(retirement_date, programming_date)
            max_arrears_months = max_arrears_years * 12
            
            if sector == "PR":
                max_arrears_months = min(max_arrears_months, 6)
            
            max_arrears = round(max_arrears_months, 0)
            
            # Use maximum arrears available
            preferred_arrears = max_arrears
            
            # Calculate adjusted balance
            preferred_max_arrears_years = preferred_arrears / 12
            new_adjusted_balance = rsa_balance * ((1 + self.discount_rate) ** -preferred_max_arrears_years)
            
            # Calculate regulatory lumpsum
            regulatory_lumpsum = rsa_balance * 0.25
            
            # Calculate 50% of final salary
            fifty_percent_salary = (validated_salary / frequency) * self.min_pension_payout
            
            # Lookup ax value and calculate nc
            ax_value = self.lookup_ax(gender, frequency, retirement_age)
            nc = ax_value - (11/24)
            nper = 2 * frequency * nc
            
            # Calculate max lumpsum
            max_lumpsum = max(0, (new_adjusted_balance + self.pv(self.monthly_rate, nper, fifty_percent_salary, fv=0, when=1)))
            
            # Calculate recommended lumpsum and use it as final lumpsum (maximum available)
            recommended_lumpsum = self.determine_lumpsum(max_lumpsum, new_adjusted_balance, regulatory_lumpsum)
            final_lumpsum = recommended_lumpsum
            
            # Calculate final monthly pension
            residual = new_adjusted_balance - final_lumpsum
            final_monthly_pension = -1 * self.pmt(self.monthly_rate, nper, residual, fv=0, when=1)
            
            # Calculate pension arrears
            pension_arrears = self.calculate_pension_arrears(frequency, preferred_arrears, final_monthly_pension)
            
            # Calculate totals
            total_benefit = final_lumpsum + pension_arrears
            annuity_premium = rsa_balance - total_benefit - final_monthly_pension
            
            return {
                'client_id': row.get('client_id', ''),
                'status': 'SUCCESS',
                'error_message': '',
                'current_age': current_age,
                'retirement_age': retirement_age,
                'validated_salary': validated_salary,
                'max_arrears_months': max_arrears,
                'final_lumpsum': final_lumpsum,
                'final_monthly_pension': final_monthly_pension,
                'pension_arrears': pension_arrears,
                'total_benefit': total_benefit,
                'annuity_premium': annuity_premium
            }
            
        except Exception as e:
            return self.create_error_result(row, str(e))
    
    def create_error_result(self, row, error_message):
        """Create error result for failed calculations"""
        return {
            'client_id': row.get('client_id', ''),
            'status': 'ERROR',
            'error_message': error_message,
            'current_age': None,
            'retirement_age': None,
            'validated_salary': None,
            'max_arrears_months': None,
            'final_lumpsum': None,
            'final_monthly_pension': None,
            'pension_arrears': None,
            'total_benefit': None,
            'annuity_premium': None
        }
    
    def process_batch(self, df):
        """Process batch of clients from DataFrame"""
        results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for index, row in df.iterrows():
            progress = (index + 1) / len(df)
            progress_bar.progress(progress)
            status_text.text(f"Processing client {index + 1}/{len(df)}: {row.get('client_id', f'Row {index + 1}')}")
            
            result = self.process_single_client(row)
            results.append(result)
        
        # Clear progress indicators
        progress_bar.empty()
        status_text.empty()
        
        # Create results DataFrame
        results_df = pd.DataFrame(results)
        
        # Merge with original data
        final_df = pd.concat([df, results_df], axis=1)
        
        return final_df, results_df


def main():
    st.set_page_config(
        page_title="Pension Calculator",
        page_icon="💰",
        layout="wide"
    )
    
    st.title("💰 Pension Calculator")
    st.markdown("Upload an Excel file with client data to calculate pension benefits")
    
    # Initialize calculator
    if 'calculator' not in st.session_state:
        with st.spinner("Loading lookup tables..."):
            calculator = PensionCalculator()
            st.session_state.calculator = calculator
    
    calculator = st.session_state.calculator
    
    # File upload section
    st.header("📁 Upload Client Data")
    
    uploaded_file = st.file_uploader(
        "Choose an Excel file",
        type=['xlsx', 'xls'],
        help="Upload an Excel file containing client pension data"
    )
    
    if uploaded_file is not None:
        try:
            # Read the uploaded file
            df = pd.read_excel(uploaded_file)
            
            st.success(f"✅ File uploaded successfully! Found {len(df)} clients.")
            
            # Display sample data
            st.subheader("📊 Data Preview")
            st.dataframe(df.head(), use_container_width=True)
            
            # Process button
            if st.button("🚀 Process Pension Calculations", type="primary"):
                with st.spinner("Processing pension calculations..."):
                    # Process the batch
                    final_df, results_df = calculator.process_batch(df)
                    
                    # Display summary
                    success_count = len(results_df[results_df['status'] == 'SUCCESS'])
                    error_count = len(results_df[results_df['status'] == 'ERROR'])
                    
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Total Clients", len(df))
                    with col2:
                        st.metric("Successful", success_count)
                    with col3:
                        st.metric("Errors", error_count)
                    
                    # Display results
                    st.subheader("📈 Results")
                    st.dataframe(final_df, use_container_width=True)
                    
                    # Show errors if any
                    if error_count > 0:
                        st.subheader("❌ Error Details")
                        error_df = results_df[results_df['status'] == 'ERROR']
                        for _, row in error_df.iterrows():
                            st.error(f"Client {row['client_id']}: {row['error_message']}")
                    
                    # Download button
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        final_df.to_excel(writer, index=False, sheet_name='Pension Results')
                    
                    output.seek(0)
                    
                    st.download_button(
                        label="📥 Download Results",
                        data=output.getvalue(),
                        file_name="pension_results.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                    
        except Exception as e:
            st.error(f"❌ Error processing file: {str(e)}")
    
    # Instructions section
    st.header("📋 Instructions")
    st.markdown("""
    ### Required Excel Columns:
    - `client_id`: Unique identifier for each client
    - `date_of_birth`: Date of birth (format: DD-MM-YYYY)
    - `retirement_date`: Retirement date (format: DD-MM-YYYY)
    - `programming_date`: Programming date (format: DD-MM-YYYY)
    - `gender`: Gender (M/F)
    - `sector`: Sector (PU/PR)
    - `frequency`: Payment frequency (4 or 12)
    - `rsa_balance`: RSA balance amount
    - `monthly_salary`: Monthly salary (for non-PU sectors or pre-cutoff dates)
    - `salary_structure`: Salary structure (for PU sector post-cutoff)
    - `grade_level`: Grade level (for PU sector post-cutoff)
    - `step`: Step (for PU sector post-cutoff)
    """)


if __name__ == "__main__":
    main()
