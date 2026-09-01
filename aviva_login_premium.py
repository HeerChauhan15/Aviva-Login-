import streamlit as st
import pandas as pd
import numpy as np
import os
import re

st.set_page_config(page_title="Insurance Premium Calculator", page_icon="💰", layout="wide")
st.title("💰 Login Aviva GCL Premium Calculator")
st.markdown("Select plan details below")

GST_RATE = 18.0  # fixed, applied on top of base rate — no loader


def normalize(s):
    return re.sub(r'[\s\-_]+', '', s.upper())


# Explicit filename map — exact files provided.
# Key: (loan_type, life_type, cover_type) -> filename on disk
RATE_FILE_MAP = {
    ("Home Loan", "Single Life", "Reducing"): "01- hl--single-reducing.xlsx",
    ("Home Loan", "Single Life", "Level"):    "HL- SINGLE.xlsx",
    ("Home Loan", "Joint Life", "Reducing"):  "HL-JOINT-REDUCING.xlsx",
    ("Home Loan", "Joint Life", "Level"):     "HL-JOINT.xlsx",
    ("LAP", "Single Life", "Level"):          "LAP - SINGLE.xlsx",
    ("LAP", "Joint Life", "Reducing"):        "LAP-JOINT-REDUCING.xlsx",
    ("LAP", "Joint Life", "Level"):           "LAP-JOINT.xlsx",
    ("LAP", "Single Life", "Reducing"):       "LAP-SINGLE- REDUCING.xlsx",
}


def find_rate_file(cover_type, life_type, loan_type, folder="."):
    """Looks up the rate file from an explicit filename map first (exact match to
    the known files). Falls back to fuzzy keyword matching if the mapped file is
    missing on disk or the combination isn't in the map — avoids hard failures
    from small naming differences."""

    mapped_name = RATE_FILE_MAP.get((loan_type, life_type, cover_type))
    if mapped_name:
        mapped_path = os.path.join(folder, mapped_name)
        if os.path.exists(mapped_path):
            return mapped_path

    # --- Fallback: fuzzy match by keywords in the filename ---
    loan_token = "HL" if loan_type == "Home Loan" else "LAP"
    life_token = "SINGLE" if life_type == "Single Life" else "JOINT"
    want_reducing = (cover_type == "Reducing")

    candidates = []
    for fname in os.listdir(folder):
        if not fname.lower().endswith((".xlsx", ".xls")):
            continue
        norm = normalize(os.path.splitext(fname)[0])
        has_reducing = "REDUCING" in norm
        if loan_token in norm and life_token in norm and has_reducing == want_reducing:
            candidates.append(fname)

    if not candidates:
        raise FileNotFoundError(
            f"No rate file found for {cover_type} / {life_type} / {loan_type}. "
            f"Expected mapped file '{mapped_name}' or a filename containing "
            f"'{loan_token}', '{life_token}'"
            + (", 'REDUCING'" if want_reducing else " (and NOT 'REDUCING')") + "."
        )
    return os.path.join(folder, candidates[0])


def load_rate_table(cover_type, life_type, loan_type):
    fpath = find_rate_file(cover_type, life_type, loan_type)
    raw = pd.read_excel(fpath, sheet_name="Sheet1", header=None)

    header_row = None
    for i, row in raw.iterrows():
        for val in row.values:
            if isinstance(val, str) and "AGE" in val.upper():
                header_row = i
                break
        if header_row is not None:
            break
    if header_row is None:
        raise ValueError(f"Could not find AGE/TERM header row in '{fpath}'.")

    df = pd.read_excel(fpath, sheet_name="Sheet1", header=header_row)
    df.columns = [str(c).strip() for c in df.columns]

    age_col = df.columns[0]
    df = df.dropna(subset=[age_col])
    df[age_col] = pd.to_numeric(df[age_col], errors='coerce')
    df = df.dropna(subset=[age_col])
    df[age_col] = df[age_col].astype(int)
    df = df.set_index(age_col)

    tenure_map = {}
    for col in df.columns:
        try:
            tenure_map[int(float(col))] = col
        except Exception:
            pass

    return df, tenure_map, fpath


def get_rate(df, tenure_map, age, tenure):
    if age not in df.index:
        raise ValueError(f"Age {age} not found in rate table.")
    if tenure not in tenure_map:
        raise ValueError(f"Tenure {tenure} yrs not found in rate table.")
    return float(df.loc[age, tenure_map[tenure]])


def apply_gst(base_rate):
    return base_rate * (1 + GST_RATE / 100.0)


def find_column(df, target):
    target_norm = target.strip().lower().replace(" ", "")
    for col in df.columns:
        if str(col).strip().lower().replace(" ", "") == target_norm:
            return col
    return None


def find_sum_assured_columns(df):
    sa_col, lo_col = None, None
    for col in df.columns:
        norm = re.sub(r'[\s_\-/]+', '', str(col).lower())
        if sa_col is None and ('sumassured' in norm or 'suminsured' in norm):
            sa_col = col
        if lo_col is None and ('loanoutstanding' in norm or 'outstandingamount' in norm
                or 'outstandingloan' in norm or norm == 'outstanding' or 'loanos' in norm or norm == 'os'):
            lo_col = col
    return sa_col, lo_col


# ============================================
# DROPDOWNS
# ============================================
col1, col2 = st.columns(2)
with col1:
    life_type = st.selectbox("Select Life Type", ["Single Life", "Joint Life"])
with col2:
    loan_type = st.selectbox("Select Loan Type", ["Home Loan", "LAP"])

cover_type = st.selectbox("Select Type of Cover", ["Level", "Reducing"])

if loan_type == "Home Loan":
    sa_min, sa_max = 100000, 6000000
    min_tenure, max_tenure = 5, 25
else:
    sa_min, sa_max = 100000, 4000000
    min_tenure, max_tenure = 2, 10

st.divider()

# ============================================
# MANUAL SECTION
# ============================================
st.subheader("🔢 Manual Rate Lookup")

col3, col4 = st.columns(2)
with col3:
    age = st.number_input("Enter Age", min_value=18, max_value=65, value=30, step=1)
with col4:
    tenure = st.number_input("Enter Tenure", min_value=min_tenure, max_value=max_tenure, value=min_tenure, step=1)
    st.caption("📅 Tenure is in Years")

sum_assured_manual = st.number_input(
    "Select Sum Assured (₹)", min_value=0, value=sa_min, step=1,
    help="Enter the exact Sum Assured for this member.", key="sa_manual"
)

if st.button("Get Rate", type="primary"):
    try:
        df_rates, tenure_map, used_file = load_rate_table(cover_type, life_type, loan_type)
        base_rate = get_rate(df_rates, tenure_map, age, tenure)
        final_rate = apply_gst(base_rate)
        premium_without_gst = base_rate * (sum_assured_manual / 100000)
        premium_with_gst = final_rate * (sum_assured_manual / 100000)
        st.success(
            f"✅ {life_type} | {loan_type} | {cover_type} Cover | Age {age} | Tenure {tenure} yrs | "
            f"Sum Assured ₹{sum_assured_manual:,} | GST {GST_RATE}% | File: {os.path.basename(used_file)}"
        )
        m1, m2 = st.columns(2)
        with m1:
            st.metric("Premium (without GST)", f"₹ {premium_without_gst:,.2f}")
        with m2:
            st.metric("Premium (with GST)", f"₹ {premium_with_gst:,.2f}")
    except Exception as e:
        st.error(f"Error: {e}")

st.divider()

# ============================================
# EXCEL UPLOAD SECTION
# ============================================
st.subheader("📂 Upload Member Data for Bulk Rate Lookup")
st.markdown(
    "Your Excel must have at least: **Name**, **Age**, **Sum Assured** (or **Loan "
    "Outstanding** if Sum Assured isn't present), and a **Tenure** column (in years)."
)
st.caption(f"Each row uses its own Sum Assured from the Excel (must be between ₹{sa_min:,} and ₹{sa_max:,}).")
st.warning("⚠️ Please make sure you have selected **Life Type**, **Loan Type**, and **Type of Cover** above before uploading your Excel file.")

uploaded_file = st.file_uploader("Upload Excel File", type=["xlsx"])

if uploaded_file is not None:
    try:
        df = pd.read_excel(uploaded_file)
        df.columns = [str(c).strip() for c in df.columns]

        st.subheader("Uploaded Data Preview")
        st.dataframe(df.head())

        min_t, max_t = min_tenure, max_tenure
        df_rates, tenure_map, used_file = load_rate_table(cover_type, life_type, loan_type)
        st.caption(f"Using rate file: {os.path.basename(used_file)}")

        name_col = find_column(df, "Name")
        age_col = find_column(df, "Age")
        tenure_col = find_column(df, "Tenure")
        sa_col, lo_col = find_sum_assured_columns(df)

        if not name_col or not age_col or not tenure_col:
            raise ValueError("Excel must contain mandatory columns: Name, Age, and Tenure.")
        if not sa_col and not lo_col:
            raise ValueError("Excel must contain a Sum Assured column (e.g. 'Sum Assured', 'Sum Insured') or a 'Loan Outstanding' column.")

        df[age_col] = pd.to_numeric(df[age_col], errors='coerce')
        df[tenure_col] = pd.to_numeric(df[tenure_col], errors='coerce')
        if sa_col:
            df[sa_col] = pd.to_numeric(df[sa_col], errors='coerce')
        if lo_col:
            df[lo_col] = pd.to_numeric(df[lo_col], errors='coerce')

        if df[tenure_col].dropna().median() > 30:
            st.info("ℹ️ Tenure values look like months — auto-converting to years.")
            df[tenure_col] = (df[tenure_col] / 12).round(0).astype('Int64')
        else:
            df[tenure_col] = df[tenure_col].round(0).astype('Int64')

        df[age_col] = df[age_col].round(0).astype('Int64')

        premiums, statuses, sa_used_list = [], [], []
        for idx, row in df.iterrows():
            try:
                r_age = int(row[age_col]) if pd.notna(row[age_col]) else None
                r_tenure = int(row[tenure_col]) if pd.notna(row[tenure_col]) else None

                r_sa = None
                if sa_col and pd.notna(row[sa_col]):
                    r_sa = float(row[sa_col])
                elif lo_col and pd.notna(row[lo_col]):
                    r_sa = float(row[lo_col])
                if r_sa is None:
                    raise ValueError("Sum Assured / Loan Outstanding value missing")

                if r_age is None or r_age < 18 or r_age > 65:
                    raise ValueError("Age must be between 18 and 65")
                if r_tenure is None or r_tenure < min_t or r_tenure > max_t:
                    raise ValueError(f"Tenure must be between {min_t} and {max_t} yrs")

                r_base = get_rate(df_rates, tenure_map, r_age, r_tenure)
                r_final = apply_gst(r_base)
                premium = round(r_final * (r_sa / 100000), 2)
                premiums.append(premium)
                statuses.append("✅")
                sa_used_list.append(r_sa)
            except Exception as e:
                premiums.append(None)
                statuses.append(f"❌ {e}")
                sa_used_list.append(None)

        df["Sum Assured Used"] = sa_used_list
        df["Premium"] = premiums
        df["Status"] = statuses

        display_sa_col = sa_col if sa_col else lo_col
        core_cols = [name_col, age_col, tenure_col, display_sa_col, "Sum Assured Used", "Premium"]
        extra_cols = [c for c in df.columns if c not in core_cols]
        df = df[core_cols + extra_cols]

        total_premium = pd.to_numeric(pd.Series(premiums), errors='coerce').sum()
        st.metric("💰 Grand Total Premium", f"₹ {total_premium:,.2f}")

        st.subheader("Rate Lookup Output")
        st.dataframe(df, use_container_width=True)

        total_row = {c: "" for c in df.columns}
        total_row[name_col] = "TOTAL PREMIUM"
        total_row["Premium"] = round(total_premium, 2)
        df_out = pd.concat([df, pd.DataFrame([total_row])], ignore_index=True)

        output_file = "Rate_Output.xlsx"
        df_out.to_excel(output_file, index=False)

        with open(output_file, "rb") as file:
            st.download_button(
                label="⬇ Download Output Excel",
                data=file,
                file_name=output_file,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

    except Exception as e:
        st.error(f"Error: {e}")
