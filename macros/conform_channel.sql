{#
  Each upstream system writes marketing channels inconsistently
  ("PPC", "google_ads", "Paid Search", ...). This macro is the single place
  that maps any raw spelling to one canonical channel. Conforming here, once,
  is what lets every downstream metric agree on what "paid_search" means.
#}
{% macro conform_channel(col) -%}
case
    when lower(trim({{ col }})) in ('ppc', 'google_ads', 'paid search', 'paid-search', 'paid_search') then 'paid_search'
    when lower(trim({{ col }})) in ('meta', 'social_paid', 'paid social', 'paid-social', 'paid_social') then 'paid_social'
    when lower(trim({{ col }})) in ('email', 'email_blast', 'newsletter') then 'email'
    when lower(trim({{ col }})) in ('seo', 'organic', 'organic search', 'organic_search') then 'organic_search'
    when lower(trim({{ col }})) in ('ref', 'word_of_mouth', 'referral') then 'referral'
    when lower(trim({{ col }})) in ('walkin', 'walk in', 'walk-in', 'walk_in') then 'walk_in'
    else 'unknown'
end
{%- endmacro %}

{% macro store_name(col) -%}
case {{ col }}
    when 1 then 'Riverside'
    when 2 then 'Highland Park'
    when 3 then 'Oakmont'
    when 4 then 'Lakeside'
    else 'Unknown'
end
{%- endmacro %}
