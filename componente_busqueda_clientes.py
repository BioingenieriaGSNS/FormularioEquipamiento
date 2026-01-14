"""
Componente de Búsqueda Inteligente de Clientes
===============================================
Módulo para integrar en formulario_ST_V14.py

Características:
- Búsqueda en tiempo real mientras se escribe
- Priorización automática por comercial
- Alta de nuevos clientes sin salir del formulario
- Validación de CUIT/DNI duplicados
- Autocompletado de datos

Autor: Desarrollo Syemed
Fecha: Enero 2026
"""

import streamlit as st
import psycopg2
from typing import List, Dict, Optional, Tuple
import re


# ============================================================================
# FUNCIONES DE BÚSQUEDA Y VALIDACIÓN
# ============================================================================

def normalizar_cuit_dni(cuit_dni: str) -> str:
    """
    Normaliza CUIT/DNI eliminando guiones y espacios.
    
    Args:
        cuit_dni: CUIT o DNI en cualquier formato
    
    Returns:
        String con solo números
    """
    if not cuit_dni:
        return ""
    return re.sub(r'[^0-9]', '', str(cuit_dni))


def buscar_clientes_db(
    texto_busqueda: str,
    tipo_cliente: Optional[str] = None,
    comercial: Optional[str] = None,
    limite: int = 15
) -> List[Dict]:
    """
    Busca clientes en la base de datos con priorización inteligente.
    
    Args:
        texto_busqueda: Texto ingresado por el usuario
        tipo_cliente: Filtro opcional por tipo (Paciente/Distribuidor/Institución)
        comercial: Nombre del comercial para priorizar resultados
        limite: Número máximo de resultados (default: 15)
    
    Returns:
        Lista de diccionarios con datos del cliente y score de relevancia
    """
    if len(texto_busqueda) < 2:
        return []
    
    try:
        from dotenv import load_dotenv
        import os
        load_dotenv()
        DATABASE_URL = os.getenv('DATABASE_URL')
        
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # Query con priorización dinámica
        query = """
        WITH clientes_relevantes AS (
            SELECT 
                id,
                tipo_cliente,
                CASE 
                    WHEN tipo_cliente = 'Paciente' THEN nombre_apellido
                    ELSE COALESCE(nombre_fantasia, razon_social)
                END as nombre_display,
                nombre_fantasia,
                razon_social,
                nombre_apellido,
                cuit_dni,
                telefono,
                direccion,
                email,
                contacto_nombre,
                comercial_asignado,
                
                -- Cálculo de score de relevancia
                (
                    -- Prioridad 1: Cliente del comercial actual (1000 pts)
                    CASE 
                        WHEN %s = ANY(comercial_asignado) THEN 1000
                        ELSE 0
                    END +
                    
                    -- Prioridad 2: Cliente visible para todos (500 pts)
                    CASE 
                        WHEN visible_para_todos = TRUE THEN 500
                        ELSE 0
                    END +
                    
                    -- Bonus por coincidencia exacta en CUIT/DNI (300 pts)
                    CASE 
                        WHEN cuit_dni = %s THEN 300
                        WHEN cuit_dni LIKE %s THEN 200
                        ELSE 0
                    END +
                    
                    -- Bonus por coincidencia en nombre (250-100 pts)
                    CASE 
                        WHEN LOWER(COALESCE(nombre_fantasia, nombre_apellido, razon_social)) LIKE LOWER(%s) THEN 250
                        WHEN LOWER(busqueda_texto) LIKE LOWER(%s) THEN 150
                        WHEN busqueda_texto ILIKE %s THEN 100
                        ELSE 0
                    END
                ) AS relevancia_score
                
            FROM clientes
            WHERE activo = TRUE
                AND (
                    -- Búsqueda por texto
                    busqueda_texto ILIKE %s
                    OR cuit_dni ILIKE %s
                )
                -- Filtro opcional por tipo
                AND (%s IS NULL OR tipo_cliente = %s)
        )
        SELECT 
            id, tipo_cliente, nombre_display, nombre_fantasia, razon_social,
            nombre_apellido, cuit_dni, telefono, direccion, email,
            contacto_nombre, comercial_asignado, relevancia_score
        FROM clientes_relevantes
        WHERE relevancia_score > 0
        ORDER BY relevancia_score DESC, nombre_display ASC
        LIMIT %s
        """
        
        # Preparar patrones de búsqueda
        texto_normalizado = normalizar_cuit_dni(texto_busqueda)
        patron_exacto = f"{texto_busqueda}"
        patron_inicio = f"{texto_busqueda}%"
        patron_parcial = f"%{texto_busqueda}%"
        
        cur.execute(query, (
            comercial,              # Para priorización por comercial
            texto_normalizado,      # CUIT/DNI exacto
            f"%{texto_normalizado}%",  # CUIT/DNI parcial
            patron_exacto,          # Nombre exacto
            patron_inicio,          # Nombre que empieza con...
            patron_parcial,         # Nombre que contiene...
            patron_parcial,         # Búsqueda general 1
            patron_parcial,         # Búsqueda general 2 (CUIT)
            tipo_cliente,           # Filtro de tipo (puede ser None)
            tipo_cliente,           # Filtro de tipo (repetido para la condición)
            limite
        ))
        
        resultados = []
        for row in cur.fetchall():
            resultados.append({
                'id': row[0],
                'tipo_cliente': row[1],
                'nombre_display': row[2],
                'nombre_fantasia': row[3],
                'razon_social': row[4],
                'nombre_apellido': row[5],
                'cuit_dni': row[6],
                'telefono': row[7],
                'direccion': row[8],
                'email': row[9],
                'contacto_nombre': row[10],
                'comercial_asignado': row[11],
                'relevancia_score': row[12]
            })
        
        cur.close()
        conn.close()
        
        return resultados
        
    except Exception as e:
        st.error(f"❌ Error en búsqueda: {e}")
        return []


def verificar_cuit_dni_existe(cuit_dni: str) -> bool:
    """
    Verifica si un CUIT/DNI ya existe en la base de datos.
    
    Args:
        cuit_dni: CUIT o DNI a verificar
    
    Returns:
        True si existe, False si no existe
    """
    cuit_normalizado = normalizar_cuit_dni(cuit_dni)
    
    if not cuit_normalizado:
        return False
    
    try:
        from dotenv import load_dotenv
        import os
        load_dotenv()
        DATABASE_URL = os.getenv('DATABASE_URL')
        
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        cur.execute("SELECT COUNT(*) FROM clientes WHERE cuit_dni = %s", (cuit_normalizado,))
        existe = cur.fetchone()[0] > 0
        
        cur.close()
        conn.close()
        
        return existe
        
    except Exception as e:
        st.error(f"❌ Error al verificar CUIT/DNI: {e}")
        return False


def insertar_cliente_nuevo(datos_cliente: Dict, comercial: Optional[str] = None) -> Optional[int]:
    """
    Inserta un nuevo cliente en la base de datos.
    
    Args:
        datos_cliente: Diccionario con datos del cliente
        comercial: Nombre del comercial que lo registra (opcional)
    
    Returns:
        ID del cliente creado o None si falla
    """
    try:
        from dotenv import load_dotenv
        import os
        load_dotenv()
        DATABASE_URL = os.getenv('DATABASE_URL')
        
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # Normalizar CUIT/DNI
        cuit_normalizado = normalizar_cuit_dni(datos_cliente.get('cuit_dni', ''))
        
        # Preparar array de comerciales
        comercial_array = [comercial] if comercial else []
        
        cur.execute("""
            INSERT INTO clientes (
                tipo_cliente,
                nombre_fantasia,
                razon_social,
                nombre_apellido,
                cuit_dni,
                telefono,
                direccion,
                email,
                contacto_nombre,
                comercial_asignado,
                visible_para_todos,
                activo
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, TRUE)
            RETURNING id
        """, (
            datos_cliente.get('tipo_cliente'),
            datos_cliente.get('nombre_fantasia'),
            datos_cliente.get('razon_social'),
            datos_cliente.get('nombre_apellido'),
            cuit_normalizado,
            datos_cliente.get('telefono'),
            datos_cliente.get('direccion'),
            datos_cliente.get('email'),
            datos_cliente.get('contacto_nombre'),
            comercial_array
        ))
        
        cliente_id = cur.fetchone()[0]
        conn.commit()
        
        cur.close()
        conn.close()
        
        return cliente_id
        
    except Exception as e:
        st.error(f"❌ Error al insertar cliente: {e}")
        if 'conn' in locals():
            conn.rollback()
        return None


# ============================================================================
# COMPONENTE PRINCIPAL DE BÚSQUEDA
# ============================================================================

def componente_selector_cliente_inteligente(
    tipo_cliente: Optional[str] = None,
    comercial: Optional[str] = None,
    key_prefix: str = "cliente",
    mostrar_filtro_tipo: bool = True
):
    """
    Componente de Streamlit para selección inteligente de clientes.
    
    Args:
        tipo_cliente: Filtro opcional por tipo de cliente (None = buscar en todos)
        comercial: Nombre del comercial para priorización
        key_prefix: Prefijo para las claves de session_state
        mostrar_filtro_tipo: Si mostrar selector de tipo de cliente
    
    Returns:
        Dict con datos del cliente seleccionado o None
    """
    # Inicializar session state
    if f'{key_prefix}_seleccionado' not in st.session_state:
        st.session_state[f'{key_prefix}_seleccionado'] = None
    if f'{key_prefix}_busqueda' not in st.session_state:
        st.session_state[f'{key_prefix}_busqueda'] = ""
    if f'{key_prefix}_modo_nuevo' not in st.session_state:
        st.session_state[f'{key_prefix}_modo_nuevo'] = False
    
    # Si ya hay cliente seleccionado, mostrarlo
    if st.session_state[f'{key_prefix}_seleccionado'] and not st.session_state.get(f'{key_prefix}_modo_nuevo'):
        cliente = st.session_state[f'{key_prefix}_seleccionado']
        
        st.success("✅ Cliente seleccionado:")
        
        col_info, col_btn = st.columns([3, 1])
        
        with col_info:
            st.markdown(f"""
            **{cliente['nombre_display']}**  
            CUIT/DNI: {cliente['cuit_dni']}  
            Tipo: {cliente['tipo_cliente']}
            """)
        
        with col_btn:
            if st.button("🔄 Cambiar", key=f"{key_prefix}_cambiar"):
                st.session_state[f'{key_prefix}_seleccionado'] = None
                st.session_state[f'{key_prefix}_busqueda'] = ""
                st.rerun()
        
        return cliente
    
    # Modo de creación de nuevo cliente
    if st.session_state[f'{key_prefix}_modo_nuevo']:
        return formulario_nuevo_cliente(tipo_cliente, comercial, key_prefix)
    
    # Mostrar búsqueda
    st.markdown("### 🔍 Búsqueda de Cliente")
    
    # Filtro de tipo (opcional)
    tipo_filtro = tipo_cliente
    if mostrar_filtro_tipo and tipo_cliente is None:
        tipo_filtro = st.selectbox(
            "Filtrar por tipo (opcional)",
            ["Todos", "Paciente", "Distribuidor", "Institución"],
            key=f"{key_prefix}_filtro_tipo"
        )
        if tipo_filtro == "Todos":
            tipo_filtro = None
    
    # Buscador con instrucciones claras
    st.markdown("💡 **Tip:** Escribe y presiona **Tab** o haz **click fuera** del campo para buscar automáticamente")
    
    col1, col2, col3 = st.columns([3, 1, 1])
    
    with col1:
        texto_busqueda = st.text_input(
            "Buscar por nombre, razón social, CUIT o DNI",
            placeholder="Ej: Hospital Central, 30718343832, Juan Pérez...",
            key=f"{key_prefix}_input",
            help="Escribe al menos 2 caracteres, luego presiona Tab o click fuera",
            label_visibility="collapsed"
        )
    
    with col2:
        # Botón de búsqueda manual como alternativa
        buscar_manual = st.button("🔍 Buscar", key=f"{key_prefix}_btn_buscar", use_container_width=True)
    
    with col3:
        if st.button("➕ Nuevo", key=f"{key_prefix}_btn_nuevo", type="primary", use_container_width=True):
            st.session_state[f'{key_prefix}_modo_nuevo'] = True
            st.rerun()
    
    # Actualizar session_state
    if texto_busqueda or buscar_manual:
        st.session_state[f'{key_prefix}_busqueda'] = texto_busqueda
    
    # Si se presionó buscar manual, forzar uso del texto actual
    texto_a_buscar = texto_busqueda if not buscar_manual else st.session_state.get(f'{key_prefix}_input', '')
    
    # Realizar búsqueda automática si hay texto
    if len(texto_a_buscar) >= 2:
        resultados = buscar_clientes_db(
            texto_busqueda=texto_a_buscar,
            tipo_cliente=tipo_filtro,
            comercial=comercial,
            limite=15
        )
        
        if resultados:
            # Separar por prioridad
            clientes_prioritarios = [r for r in resultados if r['relevancia_score'] >= 1000]
            clientes_comunes = [r for r in resultados if r['relevancia_score'] < 1000]
            
            # Mostrar clientes prioritarios
            if clientes_prioritarios:
                st.markdown("#### 🔥 Tus clientes asignados")
                for cliente in clientes_prioritarios:
                    mostrar_tarjeta_cliente(cliente, key_prefix)
            
            # Mostrar clientes comunes
            if clientes_comunes:
                st.markdown("#### 📋 Otros clientes")
                for cliente in clientes_comunes:
                    mostrar_tarjeta_cliente(cliente, key_prefix)
        else:
            st.warning("⚠️ No se encontraron clientes con ese criterio")
            st.info("💡 Puede crear un nuevo cliente con el botón 'Nuevo'")
    
    elif texto_a_buscar and len(texto_a_buscar) < 2:
        st.info("💡 Escribe al menos 2 caracteres para buscar")
    else:
        st.info("💡 Comienza a escribir para buscar un cliente o crea uno nuevo con '➕ Nuevo'")
    
    return None


def mostrar_tarjeta_cliente(cliente: Dict, key_prefix: str):
    """
    Muestra una tarjeta expandible con información del cliente.
    
    Args:
        cliente: Diccionario con datos del cliente
        key_prefix: Prefijo para keys de Streamlit
    """
    with st.expander(
        f"📌 {cliente['nombre_display']} - {cliente['cuit_dni'][:2]}-{cliente['cuit_dni'][2:-1]}-{cliente['cuit_dni'][-1]}",
        expanded=False
    ):
        col1, col2 = st.columns([3, 1])
        
        with col1:
            st.markdown(f"**Tipo:** {cliente['tipo_cliente']}")
            
            if cliente['razon_social'] and cliente['razon_social'] != cliente['nombre_display']:
                st.markdown(f"**Razón Social:** {cliente['razon_social']}")
            
            if cliente['telefono']:
                st.markdown(f"**Teléfono:** {cliente['telefono']}")
            
            if cliente['direccion']:
                st.markdown(f"**Dirección:** {cliente['direccion'][:80]}{'...' if len(cliente['direccion']) > 80 else ''}")
            
            if cliente['contacto_nombre']:
                st.markdown(f"**Contacto:** {cliente['contacto_nombre']}")
        
        with col2:
            if st.button(
                "✅ Seleccionar",
                key=f"{key_prefix}_sel_{cliente['id']}",
                type="primary",
                use_container_width=True
            ):
                st.session_state[f'{key_prefix}_seleccionado'] = cliente
                st.rerun()


def formulario_nuevo_cliente(
    tipo_cliente: Optional[str],
    comercial: Optional[str],
    key_prefix: str
) -> Optional[Dict]:
    """
    Formulario para crear un nuevo cliente.
    Si tipo_cliente es None, pregunta al usuario qué tipo quiere crear.
    
    Args:
        tipo_cliente: Tipo de cliente (si ya está definido) o None para preguntar
        comercial: Comercial que registra el cliente
        key_prefix: Prefijo para keys de Streamlit
    
    Returns:
        None (maneja el flujo internamente)
    """
    st.markdown("### ➕ Registrar Nuevo Cliente")
    
    # SIEMPRE preguntar tipo al crear nuevo (incluso si se pasó None)
    if not tipo_cliente:
        tipo_cliente = st.selectbox(
            "Tipo de cliente *",
            ["", "Paciente", "Distribuidor", "Institución"],
            key=f"{key_prefix}_nuevo_tipo",
            help="Selecciona el tipo de cliente que deseas crear"
        )
        
        if not tipo_cliente:
            st.info("💡 Selecciona el tipo de cliente para continuar")
            return None
    else:
        st.info(f"📋 Tipo de cliente: **{tipo_cliente}**")
    
    nuevo_cliente = {'tipo_cliente': tipo_cliente}
    
    # Campos según tipo
    if tipo_cliente == "Paciente":
        col1, col2 = st.columns(2)
        with col1:
            nombre_apellido = st.text_input(
                "Nombre y Apellido *",
                key=f"{key_prefix}_nuevo_nombre"
            )
            nuevo_cliente['nombre_apellido'] = nombre_apellido
        
        with col2:
            dni = st.text_input(
                "DNI * (solo números)",
                max_chars=8,
                key=f"{key_prefix}_nuevo_dni"
            )
            
            # Validación DNI
            if dni:
                if not dni.isdigit():
                    st.error("❌ El DNI debe contener solo números")
                elif len(dni) < 7:
                    st.warning("⚠️ DNI incompleto (mínimo 7 dígitos)")
                elif verificar_cuit_dni_existe(dni):
                    st.error("❌ Este DNI ya está registrado")
                else:
                    st.success("✅ DNI válido")
            
            nuevo_cliente['cuit_dni'] = dni
    
    else:  # Distribuidor o Institución
        col1, col2 = st.columns(2)
        with col1:
            nombre_fantasia = st.text_input(
                "Nombre de Fantasía *",
                key=f"{key_prefix}_nuevo_fantasia"
            )
            nuevo_cliente['nombre_fantasia'] = nombre_fantasia
        
        with col2:
            razon_social = st.text_input(
                "Razón Social *",
                key=f"{key_prefix}_nuevo_razon"
            )
            nuevo_cliente['razon_social'] = razon_social
        
        cuit = st.text_input(
            "CUIT * (11 dígitos, sin guiones)",
            max_chars=11,
            key=f"{key_prefix}_nuevo_cuit",
            placeholder="30718343832"
        )
        
        # Validación CUIT
        if cuit:
            if not cuit.isdigit():
                st.error("❌ El CUIT debe contener solo números")
            elif len(cuit) < 11:
                st.warning(f"⚠️ CUIT incompleto ({len(cuit)}/11 dígitos)")
            elif verificar_cuit_dni_existe(cuit):
                st.error("❌ Este CUIT ya está registrado")
            else:
                st.success("✅ CUIT válido")
        
        nuevo_cliente['cuit_dni'] = cuit
    
    # Campos opcionales comunes
    st.markdown("#### Información adicional (opcional)")
    
    col1, col2 = st.columns(2)
    with col1:
        telefono = st.text_input(
            "Teléfono",
            key=f"{key_prefix}_nuevo_tel",
            placeholder="1123730278"
        )
        nuevo_cliente['telefono'] = telefono
    
    with col2:
        email = st.text_input(
            "Email",
            key=f"{key_prefix}_nuevo_email",
            placeholder="contacto@empresa.com"
        )
        nuevo_cliente['email'] = email
    
    direccion = st.text_area(
        "Dirección completa",
        key=f"{key_prefix}_nuevo_dir",
        placeholder="Calle, número, localidad, provincia",
        height=80
    )
    nuevo_cliente['direccion'] = direccion
    
    if tipo_cliente in ["Distribuidor", "Institución"]:
        contacto_nombre = st.text_input(
            "Nombre de persona de contacto",
            key=f"{key_prefix}_nuevo_contacto"
        )
        nuevo_cliente['contacto_nombre'] = contacto_nombre
    
    # Botones de acción
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        pass  # Espacio
    
    with col2:
        if st.button("❌ Cancelar", key=f"{key_prefix}_cancelar", use_container_width=True):
            st.session_state[f'{key_prefix}_modo_nuevo'] = False
            st.rerun()
    
    with col3:
        # Validar campos obligatorios
        campos_validos = False
        if tipo_cliente == "Paciente":
            campos_validos = bool(nuevo_cliente.get('nombre_apellido') and 
                                 nuevo_cliente.get('cuit_dni') and 
                                 len(nuevo_cliente.get('cuit_dni', '')) >= 7)
        else:
            campos_validos = bool(nuevo_cliente.get('nombre_fantasia') and 
                                 nuevo_cliente.get('cuit_dni') and 
                                 len(nuevo_cliente.get('cuit_dni', '')) == 11)
        
        if st.button(
            "💾 Guardar",
            key=f"{key_prefix}_guardar",
            type="primary",
            disabled=not campos_validos,
            use_container_width=True
        ):
            # Insertar en BD
            cliente_id = insertar_cliente_nuevo(nuevo_cliente, comercial)
            
            if cliente_id:
                st.success("✅ Cliente registrado correctamente")
                
                # Preparar cliente para selección
                nuevo_cliente['id'] = cliente_id
                nuevo_cliente['nombre_display'] = (
                    nuevo_cliente.get('nombre_apellido') 
                    if tipo_cliente == "Paciente" 
                    else nuevo_cliente.get('nombre_fantasia')
                )
                nuevo_cliente['relevancia_score'] = 1000
                
                # Seleccionar automáticamente
                st.session_state[f'{key_prefix}_seleccionado'] = nuevo_cliente
                st.session_state[f'{key_prefix}_modo_nuevo'] = False
                st.rerun()
            else:
                st.error("❌ Error al guardar el cliente. Intente nuevamente.")
    
    if not campos_validos:
        st.warning("⚠️ Complete los campos obligatorios marcados con *")
    
    return None


# ============================================================================
# BÚSQUEDA UNIVERSAL (SIN FILTRO PREVIO DE TIPO)
# ============================================================================

def componente_selector_cliente_universal(
    comercial: Optional[str] = None,
    key_prefix: str = "cliente_universal"
) -> Optional[Dict]:
    """
    Componente para búsqueda UNIVERSAL de clientes sin preguntar tipo previamente.
    Busca en TODOS los tipos (Paciente, Distribuidor, Institución).
    Solo pregunta el tipo si el usuario quiere crear uno nuevo.
    
    Args:
        comercial: Nombre del comercial para priorización
        key_prefix: Prefijo para las claves de session_state
    
    Returns:
        Dict con datos del cliente seleccionado (incluyendo su tipo) o None
    """
    # Inicializar session state
    if f'{key_prefix}_seleccionado' not in st.session_state:
        st.session_state[f'{key_prefix}_seleccionado'] = None
    if f'{key_prefix}_modo_nuevo' not in st.session_state:
        st.session_state[f'{key_prefix}_modo_nuevo'] = False
    
    # Si ya hay cliente seleccionado, mostrarlo
    if st.session_state[f'{key_prefix}_seleccionado'] and not st.session_state.get(f'{key_prefix}_modo_nuevo'):
        cliente = st.session_state[f'{key_prefix}_seleccionado']
        
        st.success("✅ Cliente seleccionado:")
        
        col_info, col_btn = st.columns([3, 1])
        
        with col_info:
            st.markdown(f"""
            **{cliente['nombre_display']}**  
            CUIT/DNI: {cliente['cuit_dni']}  
            Tipo: {cliente['tipo_cliente']}
            """)
        
        with col_btn:
            if st.button("🔄 Cambiar", key=f"{key_prefix}_cambiar"):
                st.session_state[f'{key_prefix}_seleccionado'] = None
                st.rerun()
        
        return cliente
    
    # Modo de creación de nuevo cliente
    if st.session_state[f'{key_prefix}_modo_nuevo']:
        # Pasar None como tipo_cliente para que pregunte
        return formulario_nuevo_cliente(None, comercial, key_prefix)
    
    # Mostrar búsqueda UNIVERSAL
    st.markdown("### 🔍 Búsqueda de Cliente")
    
    
    # Buscador con instrucciones claras
    st.markdown("💡 **Tip:** Escribe y presiona **Tab** o haz **click fuera** del campo para buscar automáticamente")
    
    col1, col2, col3 = st.columns([3, 1, 1])
    
    with col1:
        texto_busqueda = st.text_input(
            "Buscar por nombre, razón social, CUIT o DNI",
            placeholder="Ej: Hospital Central, 30718343832, Juan Pérez...",
            key=f"{key_prefix}_input",
            help="Escribe al menos 2 caracteres, luego presiona Tab o click fuera",
            label_visibility="collapsed"
        )
    
    with col2:
        # Botón de búsqueda manual como alternativa
        buscar_manual = st.button("🔍 Buscar", key=f"{key_prefix}_btn_buscar", use_container_width=True)
    
    with col3:
        if st.button("➕ Nuevo", key=f"{key_prefix}_btn_nuevo", type="primary", use_container_width=True):
            st.session_state[f'{key_prefix}_modo_nuevo'] = True
            st.rerun()
    
    # Si se presionó buscar manual, forzar uso del texto actual
    texto_a_buscar = texto_busqueda if not buscar_manual else st.session_state.get(f'{key_prefix}_input', '')
    
    # Realizar búsqueda automática si hay texto
    # IMPORTANTE: Pasar tipo_cliente=None para buscar en TODOS los tipos
    if len(texto_a_buscar) >= 2:
        resultados = buscar_clientes_db(
            texto_busqueda=texto_a_buscar,
            tipo_cliente=None,  # ← BUSCAR EN TODOS LOS TIPOS
            comercial=comercial,
            limite=15
        )
        
        if resultados:
            # Separar por prioridad
            clientes_prioritarios = [r for r in resultados if r['relevancia_score'] >= 1000]
            clientes_comunes = [r for r in resultados if r['relevancia_score'] < 1000]
            
            # Mostrar clientes prioritarios
            if clientes_prioritarios:
                st.markdown("#### 🔥 Tus clientes asignados")
                for cliente in clientes_prioritarios:
                    mostrar_tarjeta_cliente(cliente, key_prefix)
            
            # Mostrar clientes comunes
            if clientes_comunes:
                st.markdown("#### 📋 Otros clientes")
                for cliente in clientes_comunes:
                    mostrar_tarjeta_cliente(cliente, key_prefix)
        else:
            st.warning("⚠️ No se encontraron clientes con ese criterio")
            st.info("💡 Puede crear un nuevo cliente con el botón '➕ Nuevo'")
    
    elif texto_a_buscar and len(texto_a_buscar) < 2:
        st.info("💡 Escribe al menos 2 caracteres para buscar")
    """ else:
        st.info("💡 Comienza a escribir para buscar un cliente o crea uno nuevo con '➕ Nuevo'") """
    
    return None


# ============================================================================
# EJEMPLO DE USO EN FORMULARIO
# ============================================================================

def ejemplo_uso():
    """
    Ejemplo de cómo integrar en el formulario principal.
    """
    st.title("Ejemplo de Integración")
    
    # Simular contexto del formulario
    comercial = st.selectbox("Comercial (simulado)", ["Ariel", "Clara", "Isabel"])
    tipo = st.selectbox("Tipo de solicitud", ["Distribuidor", "Institución", "Paciente"])
    
    st.markdown("---")
    
    # Usar el componente
    cliente_seleccionado = componente_selector_cliente_inteligente(
        tipo_cliente=tipo,
        comercial=comercial,
        key_prefix=f"ejemplo_{tipo}"
    )
    
    if cliente_seleccionado:
        st.success("Cliente listo para usar en el formulario")
        st.json(cliente_seleccionado)


if __name__ == "__main__":
    ejemplo_uso()