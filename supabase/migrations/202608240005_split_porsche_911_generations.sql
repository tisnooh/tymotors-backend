-- A 991 image cannot represent a 992 (and vice versa). Keep each Porsche 911
-- generation independently selectable and independently verifiable.

update public.vehicle_generations vg
set slug = '991',
    name = '991',
    chassis_codes = array['991'],
    year_from = 2011,
    year_to = 2019,
    display_order = 1,
    updated_at = now()
from public.vehicle_models vm
join public.brands b on b.id = vm.brand_id
where vg.vehicle_model_id = vm.id
  and b.slug = 'porsche'
  and vm.slug = '911'
  and vg.slug = '991-992';

insert into public.vehicle_generations (
  vehicle_model_id, slug, name, chassis_codes, year_from, year_to,
  display_order, is_active
)
select vm.id, '992', '992', array['992'], 2019, null, 2, true
from public.vehicle_models vm
join public.brands b on b.id = vm.brand_id
where b.slug = 'porsche' and vm.slug = '911'
on conflict (vehicle_model_id, slug) do update
set name = excluded.name,
    chassis_codes = excluded.chassis_codes,
    year_from = excluded.year_from,
    year_to = excluded.year_to,
    display_order = excluded.display_order,
    updated_at = now();

