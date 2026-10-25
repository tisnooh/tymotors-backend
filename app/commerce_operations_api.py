"""Private operations over existing admin auth; no vendor calls or visual work."""
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, Field, StrictBool, ValidationError, field_validator, model_validator

from app.commerce_models import StrictInput
from app.commerce_finance import FinanceInput, analyze_finance, group_from_evaluation
from app.supabase_rest import SupabaseError


class ImagePermissionInput(StrictInput):
    product_id: UUID
    image_url: str = Field(min_length=9,max_length=2000)
    state: Literal['pending','verified','refused','revoked'] = 'pending'
    evidence_ref: str | None = Field(default=None,min_length=1,max_length=2000)
    commercial_use: StrictBool = False
    derivatives_use: StrictBool = False
    product_match_confirmed: StrictBool = False
    marks_clearance: Literal['unknown','not_present','verified'] = 'unknown'
    countries: list[str] = Field(default_factory=list,max_length=250)
    valid_until: AwareDatetime | None = None

    @field_validator('image_url')
    @classmethod
    def secure_url(cls,value):
        p=urlsplit(value)
        if p.scheme!='https' or not p.hostname or p.username or p.password or any(c.isspace() or ord(c)<32 for c in value):
            raise ValueError('Exact HTTPS image URL without credentials required')
        return value

    @field_validator('countries')
    @classmethod
    def country_codes(cls,value):
        if len(set(value))!=len(value) or any(len(x)!=2 or not x.isascii() or not x.isalpha() or not x.isupper() for x in value):
            raise ValueError('Distinct explicit country codes required')
        return value

    @model_validator(mode='after')
    def complete_verified(self):
        if self.state=='verified' and not (self.evidence_ref and self.commercial_use and self.derivatives_use
            and self.product_match_confirmed and self.marks_clearance!='unknown' and self.countries and self.valid_until):
            raise ValueError('Complete scoped permission evidence required')
        return self


class ImagePermissionSave(StrictInput):
    data: ImagePermissionInput
    expected_updated_at: AwareDatetime | None = None


class HyperMappingInput(StrictInput):
    offer_id: UUID
    shipping_rate_id: UUID
    is_test: StrictBool = False
    state: Literal['pending','verified','rejected'] = 'pending'
    hypersku_product_ref: str | None = Field(default=None,min_length=1,max_length=200)
    hypersku_variant_ref: str | None = Field(default=None,min_length=1,max_length=200)
    equivalence_evidence_ref: str | None = Field(default=None,min_length=1,max_length=2000)
    provider_quote_ref: str | None = Field(default=None,min_length=1,max_length=2000)
    valid_until: AwareDatetime | None = None

    @model_validator(mode='after')
    def complete_verified(self):
        if self.state=='verified' and not all((self.hypersku_product_ref,self.hypersku_variant_ref,
            self.equivalence_evidence_ref,self.provider_quote_ref,self.valid_until)):
            raise ValueError('Exact equivalence and provider quote required')
        return self


class HyperMappingSave(StrictInput):
    data: HyperMappingInput
    expected_updated_at: AwareDatetime | None = None


class HyperPreparationInput(StrictInput):
    mapping_id: UUID


class QuoteFinanceOptions(StrictInput):
    inputs: dict[str,Any] = Field(default_factory=dict)


def create_operations_router(db,require_admin,get_settings):
    router=APIRouter(prefix='/api/admin/commerce',tags=['admin-operations'])

    async def rpc(name,payload):
        try:
            return await db.rpc(name,payload)
        except SupabaseError as error:
            if error.status_code in (400,403,404,409,422):
                raise HTTPException(409,'Operations evidence or source conflict') from None
            raise

    @router.post('/images/permissions')
    async def save_permission(payload:ImagePermissionSave,actor=Depends(require_admin)):
        return await rpc('commerce_save_image_permission',{'p_actor':actor['id'],
            'p_data':payload.data.model_dump(mode='json'),
            'p_expected':payload.expected_updated_at.isoformat() if payload.expected_updated_at else None})

    @router.get('/images/permissions')
    async def permissions(product_id:UUID,page:int=Query(1,ge=1),limit:int=Query(25,ge=1,le=100),_actor=Depends(require_admin)):
        return await db.page('commerce_image_permissions',params={'product_id':f'eq.{product_id}','order':'id.asc'},page=page,limit=limit)

    @router.post('/hypersku/mappings')
    async def save_mapping(payload:HyperMappingSave,actor=Depends(require_admin)):
        return await rpc('commerce_save_hypersku_mapping',{'p_actor':actor['id'],
            'p_data':payload.data.model_dump(mode='json'),
            'p_expected':payload.expected_updated_at.isoformat() if payload.expected_updated_at else None})

    @router.get('/hypersku/mappings')
    async def mappings(offer_id:UUID,page:int=Query(1,ge=1),limit:int=Query(25,ge=1,le=100),_actor=Depends(require_admin)):
        return await db.page('commerce_hypersku_mappings',params={'offer_id':f'eq.{offer_id}','order':'id.asc'},page=page,limit=limit)

    @router.post('/hypersku/tasks/{task_id}/prepare')
    async def prepare(task_id:UUID,payload:HyperPreparationInput,actor=Depends(require_admin)):
        if not get_settings().stripe_test_mode:
            raise HTTPException(409,'Internal HyperSKU preparation is currently sandbox-only')
        row=await rpc('commerce_prepare_hypersku_task',{'p_actor':actor['id'],'p_task_id':str(task_id),'p_mapping_id':str(payload.mapping_id)})
        return {k:row[k] for k in ('id','order_id','task_id','responsible_agent_id','state','is_test','external_send_allowed','expenses_authorized','packet_hash')}

    @router.get('/hypersku/preparations/{preparation_id}')
    async def preparation(preparation_id:UUID,_actor=Depends(require_admin)):
        rows=await db.select('commerce_hypersku_preparations',params={'id':f'eq.{preparation_id}','limit':1})
        if not rows: raise HTTPException(404,'Internal preparation not found')
        return rows[0]  # Private admin scope, no customer address or credentials in packet.

    @router.post('/finance/quotes/{quote_id}/analyze')
    async def finance(quote_id:UUID,payload:QuoteFinanceOptions,_actor=Depends(require_admin)):
        if 'groups' in payload.inputs:
            raise HTTPException(422,'Quote groups come only from immutable server snapshots')
        rows=await db.select('commerce_quotes',params={'id':f'eq.{quote_id}','limit':1})
        if not rows: raise HTTPException(404,'Quote not found')
        quote=rows[0]
        try:
            # Current feature is sandbox analysis: never assert that the real
            # commercial evidence was authenticated merely because a quote exists.
            groups=[group_from_evaluation(str(g['variant_id']),g['evaluation'],provenance='ASSUMPTION')
                    for g in quote['payload']['groups']]
            result=analyze_finance(FinanceInput.model_validate({**payload.inputs,'groups':groups}))
        except (ValidationError,KeyError,TypeError,ValueError):
            raise HTTPException(422,'Complete financial assumptions and three scenarios required') from None
        return {'quote_id':str(quote_id),'scope':'administrative_sandbox_analysis_not_commercial_validation',
                'source_state':quote['state'],'commercial_approval':False,'analysis':result}

    return router
