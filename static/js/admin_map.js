window.initMap = function() {
    // 地図を描画する処理を一つの関数にまとめる
    const renderMap = () => {
        const latField = document.getElementById('id_latitude');
        const lngField = document.getElementById('id_longitude');
        const mapCanvas = document.getElementById('admin-map');

        // 🛡️ 運営側の防衛的視点: 要素がまだ画面に無い場合は、100ミリ秒待ってからやり直す
        if (!latField || !lngField || !mapCanvas) {
            setTimeout(renderMap, 100);
            return;
        }

        // 初期位置（宮崎市役所付近、または登録済みの座標）
        let initialPos = { lat: 31.9077, lng: 131.4202 };
        if (latField.value && lngField.value) {
            initialPos = { lat: parseFloat(latField.value), lng: parseFloat(lngField.value) };
        }

        const map = new google.maps.Map(mapCanvas, {
            center: initialPos,
            zoom: 16,
        });

        const marker = new google.maps.Marker({
            position: initialPos,
            map: map,
            draggable: true
        });

        // 地図をクリックした時の処理
        map.addListener('click', (e) => {
            marker.setPosition(e.latLng);
            latField.value = e.latLng.lat().toFixed(6);
            lngField.value = e.latLng.lng().toFixed(6);
        });

        // マーカーをドラッグした時の処理
        marker.addListener('dragend', (e) => {
            latField.value = e.latLng.lat().toFixed(6);
            lngField.value = e.latLng.lng().toFixed(6);
        });
    };

    // 処理を開始
    renderMap();
};