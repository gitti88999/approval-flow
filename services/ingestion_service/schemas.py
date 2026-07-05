from pydantic import BaseModel, Field, model_validator
from typing import List, Optional

class LineItem(BaseModel):
    description: str = Field(..., min_length=1)
    quantity: int = Field(..., gt=0)
    unitPrice: float = Field(..., gt=0.0)

    @model_validator(mode='before')
    def check_nulls(cls, values):
        if isinstance(values, dict):
            for k, v in values.items():
                if v is None or v == "":
                    raise ValueError(f"Field '{k}' cannot be null or empty")
        return values

class InvoiceSubmission(BaseModel):
    id: str = Field(..., min_length=1)
    submitter: str = Field(..., min_length=1)
    department: str = Field(..., min_length=1)
    vendor: str = Field(..., min_length=1)
    vendorKnown: bool
    invoiceNumber: str = Field(..., min_length=1)
    currency: str = Field(..., min_length=1, max_length=3)
    category: str = Field(..., min_length=1)
    attendees: Optional[int] = None
    lineItems: List[LineItem] = Field(..., min_items=1)
    taxAmount: float = Field(..., ge=0.0)
    total: float = Field(..., gt=0.0)
    receiptPresent: bool
    date: str = Field(..., min_length=1)
    notes: Optional[str] = None

    @model_validator(mode='before')
    def check_global_nulls(cls, values):
        if isinstance(values, dict):
            required_fields = [
                'id', 'submitter', 'department', 'vendor', 'invoiceNumber', 
                'currency', 'category', 'lineItems', 'total', 'date'
            ]
            for field in required_fields:
                val = values.get(field)
                if val is None or val == "" or val == "null":
                    raise ValueError(f"Required field '{field}' cannot be null, empty, or string 'null'")
            
            # Strict enforcement for total amount inside the 'before' block to catch zero early
            if values.get('total') is not None and float(values.get('total')) <= 0:
                raise ValueError("Total amount must be greater than 0")
        return values